"""Automation service: RSS -> trends -> scheduled content -> auto publishing."""

from __future__ import annotations

from datetime import datetime, timedelta, time, timezone
import os
from typing import List, Optional

from zoneinfo import ZoneInfo

from database import db
from models import (
    AutomationSettings,
    InstagramAccount,
    RssTrend,
    ContentIdea,
    PublishedContent,
)
from encryption import decrypt_password
from instagram_service import InstagramService
from rss_service import get_trending_topics
from ai_service import summarize_trend
from media_utils import download_and_prepare_instagram_jpeg
from video_utils import animate_photo_to_mp4


DEFAULT_PUBLISH_TIMES = ["09:00", "18:00"]


def _get_tz(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo('Europe/Berlin')


def get_or_create_settings(user_id: str) -> AutomationSettings:
    s = AutomationSettings.query.filter_by(user_id=user_id).first()
    if s:
        return s
    s = AutomationSettings(
        user_id=user_id,
        enabled=False,
        rss_check_interval_minutes=240,
        publish_times=DEFAULT_PUBLISH_TIMES,
        timezone='Europe/Berlin',
        max_posts_per_day=2,
        auto_publish=False,
        use_animation=False,
    )
    db.session.add(s)
    db.session.commit()
    return s


def _parse_publish_times(times_list) -> List[time]:
    parsed: List[time] = []
    if not times_list:
        times_list = DEFAULT_PUBLISH_TIMES
    for item in times_list:
        if not item:
            continue
        s = str(item).strip()
        try:
            hh, mm = s.split(':', 1)
            parsed.append(time(int(hh), int(mm)))
        except Exception:
            continue
    parsed.sort()
    return parsed


def compute_next_publish_at(settings: AutomationSettings, now_utc: Optional[datetime] = None) -> datetime:
    tz = _get_tz(settings.timezone or 'Europe/Berlin')
    now_utc = now_utc or datetime.utcnow()
    now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)

    times = _parse_publish_times(settings.publish_times)
    if not times:
        times = _parse_publish_times(DEFAULT_PUBLISH_TIMES)

    # Find next slot today
    for t in times:
        slot_local = now_local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if slot_local > now_local:
            return slot_local.astimezone(timezone.utc).replace(tzinfo=None)

    # Otherwise first slot tomorrow
    first = times[0]
    tomorrow = (now_local + timedelta(days=1)).replace(hour=first.hour, minute=first.minute, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc).replace(tzinfo=None)


def _count_scheduled_for_day(user_id: str, day_start_utc: datetime, day_end_utc: datetime) -> int:
    return ContentIdea.query.filter(
        ContentIdea.user_id == user_id,
        ContentIdea.scheduled_at.isnot(None),
        ContentIdea.scheduled_at >= day_start_utc,
        ContentIdea.scheduled_at < day_end_utc,
        ContentIdea.status.in_(['scheduled', 'published'])
    ).count()


def create_scheduled_content_from_new_rss(user_id: str, days: int = 2, max_topics: int = 20) -> int:
    """Fetch RSS trends; store new RssTrend rows; create scheduled ContentIdea drafts."""
    settings = get_or_create_settings(user_id)
    if not settings.enabled:
        return 0

    now = datetime.utcnow()
    interval = int(settings.rss_check_interval_minutes or 240)
    if settings.last_rss_check_at and (now - settings.last_rss_check_at) < timedelta(minutes=interval):
        return 0

    trends = get_trending_topics(days=days, max_topics=max_topics)
    if not trends:
        return 0

    settings.last_rss_check_at = now
    links = [t.get('link') for t in trends if t.get('link')]
    existing = {}
    if links:
        rows = RssTrend.query.filter(RssTrend.user_id == user_id, RssTrend.link.in_(links)).all()
        existing = {r.link: r for r in rows if r.link}

    created = 0

    tz = _get_tz(settings.timezone or 'Europe/Berlin')
    now_local = now.replace(tzinfo=timezone.utc).astimezone(tz)
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)

    already_today = _count_scheduled_for_day(user_id, day_start_utc, day_end_utc)

    schedule_cursor = now

    for trend in trends:
        link = trend.get('link')
        row = existing.get(link) if link else None
        is_new = False

        if row is None:
            row = RssTrend(user_id=user_id, title=(trend.get('title') or 'No title')[:500])
            db.session.add(row)
            is_new = True

        row.content = (trend.get('content') or '')
        row.link = link
        row.source = trend.get('source')
        row.category = trend.get('category')
        row.language = trend.get('language')
        row.image_url = trend.get('image_url')
        row.matched_keywords = trend.get('matched_keywords') or []
        row.relevance_score = int(trend.get('relevance_score') or 0)
        row.published_at = trend.get('published')
        row.fetched_at = now

        # Only generate content idea for newly discovered trends
        if not is_new:
            continue

        # Respect daily limit
        if already_today >= int(settings.max_posts_per_day or 2):
            continue

        summary = summarize_trend(row.title, row.content or '')
        summary_text = (summary.get('summary') or '').strip() or row.title
        relevance_text = (summary.get('relevance') or '').strip()

        hashtags = ['#fliesen', '#badsanierung', '#frankfurt', '#bathroom', '#renovierung', '#interiordesign']
        for kw in (row.matched_keywords or [])[:6]:
            s = ''.join(ch for ch in str(kw) if ch.isalnum() or ch in ['_', '-'])
            if not s:
                continue
            tag = '#' + s.lower().replace('-', '').replace('_', '')
            if tag not in hashtags and len(tag) <= 30:
                hashtags.append(tag)

        cta = (
            "\n\n📩 Хочете сучасну ванну кімнату у Франкфурті та околицях? "
            "Напишіть нам — зробимо безкоштовну консультацію та розрахунок."
        )
        parts = [f"🔥 {row.title}", summary_text]
        if relevance_text:
            parts.append(relevance_text)
        caption = "\n\n".join([p for p in parts if p]) + cta

        scheduled_at = compute_next_publish_at(settings, now_utc=schedule_cursor)
        schedule_cursor = scheduled_at + timedelta(minutes=1)

        idea = ContentIdea(
            user_id=user_id,
            trend_id=row.id,
            title=row.title,
            caption=caption,
            hashtags=hashtags,
            content_type='trend_based',
            status='scheduled' if settings.auto_publish else 'draft',
            scheduled_at=scheduled_at if settings.auto_publish else None,
            generated_image_url=row.image_url,
        )
        db.session.add(idea)
        created += 1
        already_today += 1

    db.session.commit()
    return created


def publish_due_content(user_id: str, limit: int = 3) -> int:
    settings = get_or_create_settings(user_id)
    if not (settings.enabled and settings.auto_publish):
        return 0

    now = datetime.utcnow()
    settings.last_publish_run_at = now
    due = (ContentIdea.query
           .filter(ContentIdea.user_id == user_id,
                   ContentIdea.status == 'scheduled',
                   ContentIdea.scheduled_at.isnot(None),
                   ContentIdea.scheduled_at <= now)
           .order_by(ContentIdea.scheduled_at.asc())
           .limit(limit)
           .all())

    if not due:
        return 0

    account = InstagramAccount.query.filter_by(user_id=user_id, is_active=True).first()
    if not account:
        return 0

    password = decrypt_password(account.instagram_password)
    if not password:
        settings.last_error = 'decrypt_failed: set ENCRYPTION_KEY (or same SECRET_KEY) to decrypt instagram_password'
        db.session.commit()
        return 0

    service = InstagramService(account.instagram_username, password)
    ok, msg = service.login()
    if not ok:
        # leave ideas as scheduled; user can fix login
        return 0

    upload_folder = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(upload_folder, exist_ok=True)

    rendered_folder = os.path.join(upload_folder, 'rendered')
    os.makedirs(rendered_folder, exist_ok=True)

    published_count = 0

    for idea in due:
        try:
            caption = (idea.caption or '').strip()
            tags = idea.hashtags or []
            if tags:
                caption = caption + "\n\n" + ' '.join(tags)

            image_url = idea.generated_image_url
            if not image_url:
                idea.status = 'failed'
                db.session.commit()
                continue

            local_jpg = download_and_prepare_instagram_jpeg(image_url, upload_folder)

            music_path = None
            if settings.music_file_path:
                candidate = settings.music_file_path
                if not os.path.isabs(candidate):
                    candidate = os.path.join(os.path.dirname(__file__), candidate)
                if os.path.exists(candidate):
                    music_path = candidate

            if settings.use_animation:
                duration_seconds = int(settings.animation_duration_seconds or 8)
                fps = int(settings.animation_fps or 30)
                video_path = os.path.join(rendered_folder, f"idea_{idea.id}.mp4")
                animate_photo_to_mp4(
                    image_path=local_jpg,
                    output_path=video_path,
                    duration_seconds=duration_seconds,
                    fps=fps,
                    audio_path=music_path,
                    target_size=(1080, 1920),
                )
                success, result = service.publish_reel(caption, video_path)
                media_basename = os.path.basename(video_path)
                content_type = 'reel'
            else:
                success, result = service.publish_post(caption, local_jpg)
                media_basename = os.path.basename(local_jpg)
                content_type = 'post'

            pub = PublishedContent(
                user_id=user_id,
                instagram_account_id=account.id,
                content_type=content_type,
                caption=caption,
                media_urls=[media_basename],
                status='published' if success else 'failed',
                instagram_media_id=result if success else None,
                error_message=None if success else str(result),
                published_at=datetime.utcnow() if success else None,
            )
            db.session.add(pub)

            if success:
                idea.status = 'published'
                idea.published_at = datetime.utcnow()
                published_count += 1
            else:
                idea.status = 'failed'

            db.session.commit()

            try:
                os.remove(local_jpg)
            except Exception:
                pass

            if settings.use_animation:
                try:
                    os.remove(os.path.join(rendered_folder, f"idea_{idea.id}.mp4"))
                except Exception:
                    pass

        except Exception as e:
            idea.status = 'failed'
            db.session.commit()

    return published_count
