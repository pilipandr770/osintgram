"""DM assistant service: poll Instagram Direct inbox and auto-reply using OpenAI.

Safety defaults:
- Per-account enable switch.
- Daily cap.
- First-seen threads are not replied to unless explicitly allowed.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from database import db
from models import (
    InstagramAccount,
    DmAssistantSettings,
    DmThreadState,
    DmMessage,
)
from encryption import decrypt_password
from instagram_service import InstagramService
from ai_service import generate_dm_reply


def _now_utc() -> datetime:
    return datetime.utcnow()


def _as_datetime(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # instagrapi sometimes uses unix seconds
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


def _message_to_row(
    user_id: str,
    account_id: str,
    thread_id: str,
    msg: Any,
    direction: str,
) -> Dict:
    item_id = str(_get_attr(msg, ['id', 'item_id', 'pk', 'uuid'], default=''))
    text = _get_attr(msg, ['text', 'message', 'content'], default='')
    ts = _as_datetime(_get_attr(msg, ['timestamp', 'created_at', 'time'], default=None))

    sender_user_id = str(_get_attr(msg, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
    sender_username = _get_attr(msg, ['username', 'sender_username'], default=None)

    # Some instagrapi message objects have .user or .sender with username
    user_obj = _get_attr(msg, ['user', 'sender', 'from_user'], default=None)
    if not sender_username and user_obj is not None:
        sender_username = _get_attr(user_obj, ['username'], default=None)

    return {
        'user_id': user_id,
        'instagram_account_id': account_id,
        'thread_id': thread_id,
        'item_id': item_id,
        'direction': direction,
        'sender_user_id': sender_user_id,
        'sender_username': sender_username,
        'text': text,
        'sent_at': ts,
    }


def _count_replies_today(user_id: str, account_id: str) -> int:
    today = date.today()
    return DmMessage.query.filter(
        DmMessage.user_id == user_id,
        DmMessage.instagram_account_id == account_id,
        DmMessage.direction == 'out',
        db.func.date(DmMessage.created_at) == today,
    ).count()


def poll_and_reply_for_user(user_id: str, threads_limit: int = 10, messages_per_thread: int = 20) -> int:
    """Poll all enabled DM assistant settings for a user and reply when needed."""

    settings_list = DmAssistantSettings.query.filter_by(user_id=user_id, enabled=True).all()
    if not settings_list:
        return 0

    total_replied = 0

    for settings in settings_list:
        settings.last_run_at = _now_utc()
        settings.last_error = None
        try:
            replied = _poll_and_reply_for_account(
                user_id=user_id,
                account_id=settings.instagram_account_id,
                settings=settings,
                threads_limit=threads_limit,
                messages_per_thread=messages_per_thread,
            )
            total_replied += replied
            db.session.commit()
            if settings.last_error:
                print(f"DM assistant: user={user_id} account={settings.instagram_account_id} error={settings.last_error}")
        except Exception as e:
            settings.last_error = str(e)
            db.session.commit()
            print(f"DM assistant: user={user_id} account={settings.instagram_account_id} exception={settings.last_error}")

    return total_replied


def _poll_and_reply_for_account(
    user_id: str,
    account_id: str,
    settings: DmAssistantSettings,
    threads_limit: int,
    messages_per_thread: int,
) -> int:
    account = InstagramAccount.query.filter_by(id=account_id, user_id=user_id).first()
    if not account:
        return 0

    password = decrypt_password(account.instagram_password)
    if not password:
        settings.last_error = 'decrypt_failed: set ENCRYPTION_KEY (or same SECRET_KEY) to decrypt instagram_password'
        return 0

    service = InstagramService(account.instagram_username, password)
    ok, login_msg = service.login()
    if not ok:
        settings.last_error = f'login_failed: {login_msg}'
        return 0

    client = service.client
    my_user_id = str(getattr(client, 'user_id', '') or '')

    daily_sent = _count_replies_today(user_id, account_id)
    daily_cap = int(settings.max_replies_per_day or 20)
    if daily_sent >= daily_cap:
        return 0

    replied_count = 0

    try:
        threads = client.direct_threads(amount=int(threads_limit or 10))
    except Exception as e:
        settings.last_error = f'direct_threads_failed: {e}'
        return 0
    for th in threads:
        if daily_sent + replied_count >= daily_cap:
            break

        thread_id = str(_get_attr(th, ['id', 'thread_id', 'pk'], default=''))
        if not thread_id:
            continue

        state = DmThreadState.query.filter_by(instagram_account_id=account_id, thread_id=thread_id).first()

        try:
            msgs = client.direct_messages(thread_id, amount=int(messages_per_thread or 20))
        except Exception as e:
            # Do not abort whole run on one thread
            settings.last_error = f'direct_messages_failed(thread={thread_id}): {e}'
            continue
        if not msgs:
            continue

        # Ensure chronological order
        msgs_sorted = sorted(msgs, key=lambda m: (_get_attr(m, ['timestamp', 'created_at', 'time'], default=0) or 0))
        newest = msgs_sorted[-1]
        newest_id = str(_get_attr(newest, ['id', 'item_id', 'pk', 'uuid'], default=''))

        if state is None:
            state = DmThreadState(user_id=user_id, instagram_account_id=account_id, thread_id=thread_id)
            db.session.add(state)
            # First time: set cursor, optionally do not reply
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            if not settings.reply_to_existing_threads:
                continue

        # Find messages after last_seen_item_id
        new_msgs: List[Any] = []
        seen = state.last_seen_item_id
        if seen:
            passed = False
            for m in msgs_sorted:
                mid = str(_get_attr(m, ['id', 'item_id', 'pk', 'uuid'], default=''))
                if passed:
                    new_msgs.append(m)
                    continue
                if mid == seen:
                    passed = True
            # If last seen isn't in the window, treat as no new (cursor too old)
            if seen and not passed:
                state.last_seen_item_id = newest_id
                state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
                db.session.commit()
                continue
        else:
            # No cursor: reply only to newest
            new_msgs = [newest]

        # Only respond if there is an inbound message from other user
        inbound = []
        for m in new_msgs:
            sender_id = str(_get_attr(m, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
            if my_user_id and sender_id == my_user_id:
                continue
            text = (_get_attr(m, ['text', 'message', 'content'], default='') or '').strip()
            if text:
                inbound.append(m)

        if not inbound:
            # Update cursor to newest to avoid re-processing
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            continue

        last_in = inbound[-1]

        # Persist fetched messages (best-effort)
        for m in new_msgs:
            try:
                sender_id = str(_get_attr(m, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
                direction = 'out' if (my_user_id and sender_id == my_user_id) else 'in'
                row = _message_to_row(user_id, account_id, thread_id, m, direction)
                if not row['item_id']:
                    continue
                exists = DmMessage.query.filter_by(instagram_account_id=account_id, thread_id=thread_id, item_id=row['item_id']).first()
                if not exists:
                    db.session.add(DmMessage(**row))
                    db.session.commit()
            except Exception:
                db.session.rollback()

        # Build short context from DB
        history_rows = (DmMessage.query
                        .filter_by(instagram_account_id=account_id, thread_id=thread_id)
                        .order_by(DmMessage.created_at.desc())
                        .limit(12)
                        .all())
        history_rows.reverse()

        convo: List[Dict[str, str]] = []
        for r in history_rows:
            if not r.text:
                continue
            role = 'assistant' if r.direction == 'out' else 'user'
            convo.append({'role': role, 'content': r.text})

        # Generate reply
        reply_text = generate_dm_reply(settings.system_instructions or '', convo, language=settings.language or 'ru')
        reply_text = (reply_text or '').strip()
        if not reply_text:
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            continue

        # Send
        try:
            result = client.direct_send(reply_text, thread_ids=[thread_id])
        except Exception as e:
            settings.last_error = f'direct_send_failed(thread={thread_id}): {e}'
            # Update cursor so we don't retry the same inbound endlessly
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            continue

        # Save outbound message as well
        out_item_id = str(_get_attr(result, ['id', 'item_id', 'pk', 'uuid'], default=''))
        out = DmMessage(
            user_id=user_id,
            instagram_account_id=account_id,
            thread_id=thread_id,
            item_id=out_item_id or f"local_{random.randint(100000, 999999)}_{int(time.time())}",
            direction='out',
            sender_user_id=my_user_id,
            sender_username=account.instagram_username,
            text=reply_text,
            sent_at=_now_utc(),
            processed=True,
        )
        db.session.add(out)

        # Mark inbound as processed
        in_item_id = str(_get_attr(last_in, ['id', 'item_id', 'pk', 'uuid'], default=''))
        try:
            in_row = DmMessage.query.filter_by(instagram_account_id=account_id, thread_id=thread_id, item_id=in_item_id).first()
            if in_row:
                in_row.processed = True
                in_row.reply_text = reply_text
                in_row.replied_at = _now_utc()
        except Exception:
            pass

        # Update cursor
        state.last_seen_item_id = newest_id
        state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))

        db.session.commit()

        replied_count += 1

        # Delay for safety
        lo = int(settings.min_delay_seconds or 15)
        hi = int(settings.max_delay_seconds or 45)
        lo = max(5, min(lo, 300))
        hi = max(lo, min(hi, 600))
        time.sleep(random.randint(lo, hi))

    return replied_count
