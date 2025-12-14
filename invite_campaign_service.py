"""Invite campaign service: automated outreach in Instagram Direct.

Features:
- Per-account enable switch and daily cap.
- Multi-step program with offsets (hours since enrollment).
- Repeat protection via recipients table (unique per account+recipient).
- Stops a recipient when an inbound reply is detected.

This module is designed to be run from a background worker (see invite_campaign_runner.py).
"""

from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo
from datetime import timezone

from database import db
from models import (
    Follower,
    InstagramAccount,
    InviteCampaignRecipient,
    InviteCampaignSend,
    InviteCampaignSettings,
    DmMessage,
)
from encryption import decrypt_password
from instagram_service import InstagramService


def _now_utc() -> datetime:
    return datetime.utcnow()


def _is_within_allowed_hours(settings: InviteCampaignSettings, now_utc: Optional[datetime] = None) -> bool:
    """Return True if current local time (settings.timezone) is inside allowed [start,end) hours."""
    now_utc = now_utc or _now_utc()
    tz_name = (getattr(settings, 'timezone', None) or 'Europe/Berlin')
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Some Windows/Python builds may not have tzdata; fall back to UTC.
        tz = timezone.utc

    start = int(getattr(settings, 'allowed_start_hour', 8) or 8)
    end = int(getattr(settings, 'allowed_end_hour', 22) or 22)
    start = max(0, min(start, 23))
    end = max(0, min(end, 23))

    # start == end means 24h allowed
    if start == end:
        return True

    local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    h = int(local.hour)

    if start < end:
        return start <= h < end
    # wrap across midnight
    return (h >= start) or (h < end)


def _as_datetime(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.utcfromtimestamp(float(ts))
    except Exception:
        return None


def _get_attr(obj: Any, names: List[str], default=None):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default


def _count_sent_today(user_id: str, account_id: str) -> int:
    today = date.today()
    return InviteCampaignSend.query.filter(
        InviteCampaignSend.user_id == user_id,
        InviteCampaignSend.instagram_account_id == account_id,
        InviteCampaignSend.status == 'sent',
        db.func.date(InviteCampaignSend.sent_at) == today,
    ).count()


def _parse_audience_type(audience_type: str) -> Tuple[str, str]:
    """Return (segment, group).

    segment: target|frankfurt|all
    group: any|new|own

    We store this as a single string for backward compatibility, e.g.:
    - 'target' (legacy)
    - 'target:new' (only contacts collected from competitors)
    - 'target:own' (only contacts collected from our own account)
    """
    raw = (audience_type or 'target').strip().lower()
    if ':' in raw:
        seg, grp = raw.split(':', 1)
    else:
        seg, grp = raw, 'any'

    seg = seg if seg in {'target', 'frankfurt', 'all'} else 'target'
    if grp in {'new', 'prospects'}:
        grp = 'new'
    elif grp in {'own', 'mine', 'my'}:
        grp = 'own'
    else:
        grp = 'any'

    return seg, grp


def _pick_new_followers(
    user_id: str,
    audience_type: str,
    account_id: str,
    my_account_username: str,
    limit: int,
) -> List[Follower]:
    # Base follower query
    q = Follower.query.filter(Follower.user_id == user_id)

    segment, group = _parse_audience_type(audience_type)
    if segment == 'frankfurt':
        q = q.filter(Follower.is_frankfurt_region.is_(True))
    elif segment == 'target':
        q = q.filter(Follower.is_target_audience.is_(True))
    else:
        # all
        pass

    # Group split: "new contacts" vs "our followers"
    my_u = (my_account_username or '').strip().lstrip('@').lower()
    if my_u:
        if group == 'new':
            q = q.filter(db.func.lower(Follower.source_account_username) != my_u)
        elif group == 'own':
            q = q.filter(db.func.lower(Follower.source_account_username) == my_u)

    # Exclude already-enrolled recipients for this account
    subq = db.session.query(InviteCampaignRecipient.recipient_username).filter(
        InviteCampaignRecipient.instagram_account_id == account_id
    )
    q = q.filter(~Follower.username.in_(subq))

    # Prefer newest collected first (simple heuristic)
    q = q.order_by(Follower.collected_at.desc())

    return q.limit(int(limit)).all()


def _ensure_recipient_enrolled(
    user_id: str,
    account_id: str,
    recipient_username: str,
    recipient_user_id: Optional[str] = None,
) -> Optional[InviteCampaignRecipient]:
    existing = InviteCampaignRecipient.query.filter_by(
        instagram_account_id=account_id,
        recipient_username=recipient_username,
    ).first()
    if existing:
        return existing

    now = _now_utc()
    rec = InviteCampaignRecipient(
        user_id=user_id,
        instagram_account_id=account_id,
        recipient_username=recipient_username,
        recipient_user_id=recipient_user_id,
        status='active',
        current_step=0,
        enrolled_at=now,
        next_send_at=now,
    )
    db.session.add(rec)
    try:
        db.session.commit()
        return rec
    except Exception:
        db.session.rollback()
        # likely unique constraint race
        return InviteCampaignRecipient.query.filter_by(
            instagram_account_id=account_id,
            recipient_username=recipient_username,
        ).first()


def _format_template(template: str, follower: Optional[Follower]) -> str:
    username = follower.username if follower else ''
    name = ''
    if follower and follower.full_name:
        name = (follower.full_name.split(' ')[0] or '').strip()
    if not name:
        name = username

    msg = template
    msg = msg.replace('{username}', username)
    msg = msg.replace('{name}', name)
    return msg


def _has_inbound_reply(
    account_id: str,
    thread_id: str,
    last_outbound_at: datetime,
    my_user_id: str,
    client: Any,
) -> bool:
    # Fast path: if DM assistant already saved inbound messages
    try:
        inbound = (DmMessage.query
                   .filter_by(instagram_account_id=account_id, thread_id=thread_id, direction='in')
                   .filter(DmMessage.sent_at.isnot(None))
                   .filter(DmMessage.sent_at > last_outbound_at)
                   .first())
        if inbound is not None:
            return True
    except Exception:
        db.session.rollback()

    # Fallback: query Instagram thread
    try:
        msgs = client.direct_messages(thread_id, amount=20)
    except Exception:
        return False

    for m in msgs or []:
        sender_id = str(_get_attr(m, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
        if my_user_id and sender_id == my_user_id:
            continue
        text = (_get_attr(m, ['text', 'message', 'content'], default='') or '').strip()
        if not text:
            continue
        ts = _as_datetime(_get_attr(m, ['timestamp', 'created_at', 'time'], default=None))
        if ts and ts > last_outbound_at:
            return True

    return False


def _compute_next_send_at(enrolled_at: datetime, steps: List[Dict[str, Any]], next_step_index: int) -> Optional[datetime]:
    if next_step_index >= len(steps):
        return None
    offset_hours = steps[next_step_index].get('offset_hours', 0)
    try:
        offset_hours = int(offset_hours)
    except Exception:
        offset_hours = 0
    return enrolled_at + timedelta(hours=max(0, offset_hours))


def _pick_due_recipient(user_id: str, account_id: str) -> Optional[InviteCampaignRecipient]:
    now = _now_utc()
    return (InviteCampaignRecipient.query
            .filter_by(user_id=user_id, instagram_account_id=account_id, status='active')
            .filter(InviteCampaignRecipient.next_send_at.isnot(None))
            .filter(InviteCampaignRecipient.next_send_at <= now)
            .order_by(InviteCampaignRecipient.next_send_at.asc())
            .first())


def run_invite_campaign_for_user(user_id: str, max_per_account: Optional[int] = None) -> Dict[str, int]:
    """Run one campaign cycle for a user across all enabled accounts."""

    stats = {'accounts': 0, 'sent': 0, 'stopped': 0, 'completed': 0, 'failed': 0}

    settings_list = InviteCampaignSettings.query.filter_by(user_id=user_id, enabled=True).all()
    if not settings_list:
        return stats

    for settings in settings_list:
        settings.last_run_at = _now_utc()
        settings.last_error = None
        try:
            s, stopped, completed, failed = _run_for_account(user_id, settings, max_per_account=max_per_account)
            stats['accounts'] += 1
            stats['sent'] += s
            stats['stopped'] += stopped
            stats['completed'] += completed
            stats['failed'] += failed
            db.session.commit()
        except Exception as e:
            settings.last_error = str(e)
            db.session.commit()

    return stats


def _run_for_account(
    user_id: str,
    settings: InviteCampaignSettings,
    max_per_account: Optional[int],
) -> Tuple[int, int, int, int]:
    account_id = settings.instagram_account_id
    account = InstagramAccount.query.filter_by(id=account_id, user_id=user_id).first()
    if not account:
        return 0, 0, 0, 0

    steps = settings.steps or []
    if not isinstance(steps, list) or not steps:
        return 0, 0, 0, 0

    # Day/Night режим: не відправляємо в "нічні" години
    if not _is_within_allowed_hours(settings):
        return 0, 0, 0, 0

    password = decrypt_password(account.instagram_password)
    if not password:
        settings.last_error = 'decrypt_failed: set ENCRYPTION_KEY (or same SECRET_KEY) to decrypt instagram_password'
        db.session.commit()
        return 0, 0, 0, 0

    service = InstagramService(account.instagram_username, password)
    ok, _ = service.login()
    if not ok:
        return 0, 0, 0, 0

    client = service.client
    my_user_id = str(getattr(client, 'user_id', '') or '')

    daily_cap = int(settings.max_sends_per_day or 20)
    already_sent = _count_sent_today(user_id, account_id)
    remaining = max(0, daily_cap - already_sent)
    if max_per_account is not None:
        remaining = min(remaining, int(max_per_account))
    if remaining <= 0:
        return 0, 0, 0, 0

    min_delay = int(settings.min_delay_seconds or 1)
    max_delay = int(settings.max_delay_seconds or min_delay)
    if max_delay < min_delay:
        max_delay = min_delay

    # Anti-spam: for "new contacts" outreach, enforce at least 3 minutes between sends.
    _, audience_group = _parse_audience_type(getattr(settings, 'audience_type', None) or 'target')
    if audience_group == 'new':
        min_delay = max(min_delay, 180)
        max_delay = max(max_delay, min_delay)

    sent = 0
    stopped = 0
    completed = 0
    failed = 0

    for _ in range(remaining):
        rec = _pick_due_recipient(user_id, account_id)
        if rec is None:
            # Enroll a few new followers and try again
            new_followers = _pick_new_followers(
                user_id=user_id,
                audience_type=settings.audience_type or 'target',
                account_id=account_id,
                my_account_username=account.instagram_username,
                limit=25,
            )
            if not new_followers:
                break
            for f in new_followers:
                _ensure_recipient_enrolled(
                    user_id=user_id,
                    account_id=account_id,
                    recipient_username=f.username,
                    recipient_user_id=f.instagram_user_id,
                )
            rec = _pick_due_recipient(user_id, account_id)
            if rec is None:
                break

        # Stop if user replied
        if settings.stop_on_inbound_reply and rec.thread_id and rec.last_outbound_at:
            if _has_inbound_reply(
                account_id=account_id,
                thread_id=rec.thread_id,
                last_outbound_at=rec.last_outbound_at,
                my_user_id=my_user_id,
                client=client,
            ):
                rec.status = 'stopped'
                rec.completed_at = _now_utc()
                stopped += 1
                db.session.commit()
                continue

        step_index = int(rec.current_step or 0)
        if step_index >= len(steps):
            rec.status = 'completed'
            rec.completed_at = _now_utc()
            rec.next_send_at = None
            completed += 1
            db.session.commit()
            continue

        follower = Follower.query.filter_by(user_id=user_id, username=rec.recipient_username).first()
        template = str(steps[step_index].get('template', '') or '').strip()
        if not template:
            # Skip empty template steps
            rec.current_step = step_index + 1
            rec.next_send_at = _compute_next_send_at(rec.enrolled_at or _now_utc(), steps, rec.current_step)
            if rec.current_step >= len(steps):
                rec.status = 'completed'
                rec.completed_at = _now_utc()
                rec.next_send_at = None
                completed += 1
            db.session.commit()
            continue

        msg_text = _format_template(template, follower)

        result = service.send_direct_message(rec.recipient_username, msg_text)
        success = bool(result.get('success'))
        thread_id = result.get('thread_id')
        err = result.get('error')

        send_row = InviteCampaignSend(
            user_id=user_id,
            instagram_account_id=account_id,
            recipient_username=rec.recipient_username,
            recipient_user_id=rec.recipient_user_id,
            thread_id=thread_id or rec.thread_id,
            step_index=step_index,
            message_text=msg_text,
            status='sent' if success else 'failed',
            error_message=None if success else (err or 'send_failed'),
            sent_at=_now_utc(),
        )
        db.session.add(send_row)

        if success:
            rec.thread_id = thread_id or rec.thread_id
            rec.last_outbound_at = _now_utc()
            rec.last_error = None
            rec.current_step = step_index + 1
            next_at = _compute_next_send_at(rec.enrolled_at or _now_utc(), steps, rec.current_step)
            if next_at is None:
                rec.status = 'completed'
                rec.completed_at = _now_utc()
                rec.next_send_at = None
                completed += 1
            else:
                rec.next_send_at = next_at
            sent += 1
            db.session.commit()

            # Delay between sends
            delay = random.randint(max(1, min_delay), max(1, max_delay))
            time.sleep(delay)
        else:
            # Back off this recipient; keep active to retry later
            rec.last_error = str(err or 'send_failed')
            rec.next_send_at = _now_utc() + timedelta(hours=12)
            failed += 1
            db.session.commit()

            # If rate-limited, stop processing further this cycle
            if isinstance(err, str) and ('rate_limit' in err or 'feedback_required' in err):
                break

    return sent, stopped, completed, failed
