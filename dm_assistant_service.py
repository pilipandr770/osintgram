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
from datetime import timedelta
import os
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


# If a thread is seen for the first time, we normally avoid replying to prevent
# blasting old inboxes. However, if the latest inbound message is recent we can
# safely treat it as a "new" conversation and reply immediately.
FIRST_SEEN_REPLY_WINDOW_MINUTES = 10


def _env_truthy(name: str, default: str = 'false') -> bool:
    return os.environ.get(name, default).lower() in {'1', 'true', 'yes'}


def _is_debug() -> bool:
    # Read dynamically so toggling env + restart is always effective,
    # and to avoid import-time ordering pitfalls.
    return _env_truthy('DM_ASSISTANT_DEBUG', 'false')


def _auto_approve_requests() -> bool:
    return _env_truthy('DM_ASSISTANT_AUTO_APPROVE_REQUESTS', 'false')


def _debug(msg: str) -> None:
    if _is_debug():
        print(msg)


def _extract_threads_from_inbox_obj(obj: Any) -> List[Any]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return obj.get('threads') or []
    threads = getattr(obj, 'threads', None) or []
    if threads:
        return threads
    inbox = getattr(obj, 'inbox', None)
    return getattr(inbox, 'threads', None) or []


def _get_threads_best_effort(client: Any, limit: int) -> List[Any]:
    """Try multiple instagrapi methods because availability differs by version."""
    limit = int(limit or 10)
    methods = [
        ('direct_threads', {'amount': limit}),
        ('direct_inbox', {'amount': limit}),
        ('direct_inbox_v1', {'amount': limit}),
    ]

    last_err = None
    for name, kwargs in methods:
        if not hasattr(client, name):
            continue
        try:
            fn = getattr(client, name)
            try:
                obj = fn(**kwargs)
            except TypeError:
                obj = fn()
            threads = _extract_threads_from_inbox_obj(obj)
            if threads is not None:
                return threads
        except Exception as e:
            last_err = e
            continue

    if last_err is not None:
        raise last_err
    return []


def _persist_messages_best_effort(
    user_id: str,
    account_id: str,
    thread_id: str,
    messages: List[Any],
    my_user_id: str,
    max_items: int = 12,
) -> None:
    """Persist a small window of messages for context/audit (best-effort)."""
    if not messages:
        return
    window = messages[-max_items:] if len(messages) > max_items else messages

    try:
        added = 0
        skipped_no_id = 0
        for m in window:
            sender_id = str(_get_attr(m, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
            direction = 'out' if (my_user_id and sender_id == my_user_id) else 'in'
            row = _message_to_row(user_id, account_id, thread_id, m, direction)
            if not row.get('item_id'):
                skipped_no_id += 1
                continue

            exists = (DmMessage.query
                      .filter_by(instagram_account_id=account_id, thread_id=thread_id, item_id=row['item_id'])
                      .first())
            if exists:
                continue
            db.session.add(DmMessage(**row))
            added += 1

        db.session.commit()
        if _is_debug() and (added or skipped_no_id):
            _debug(
                f"DM assistant: persist account_id={account_id} thread={thread_id} added={added} skipped_no_id={skipped_no_id}"
            )
    except Exception:
        db.session.rollback()


def _now_utc() -> datetime:
    return datetime.utcnow()


def _as_datetime(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # instagrapi sometimes uses unix seconds, sometimes milliseconds.
        # Heuristics:
        # - seconds ~ 1e9..1e10
        # - ms ~ 1e12..1e13
        # - us ~ 1e15..
        value = float(ts)
        if value > 1e14:
            value = value / 1_000_000.0
        elif value > 1e11:
            value = value / 1_000.0
        return datetime.utcfromtimestamp(value)
    except Exception:
        return None


def _try_approve_thread(client: Any, thread_id: str) -> bool:
    """Best-effort approval of a pending/message-request thread.

    Returns True if an approve call was attempted and didn't raise.
    """
    if not thread_id:
        return False

    approve_methods = [
        'direct_thread_approve',
        'direct_thread_approve_v1',
        'direct_pending_thread_approve',
        'direct_pending_thread_approve_v1',
    ]
    for name in approve_methods:
        if not hasattr(client, name):
            continue
        try:
            getattr(client, name)(thread_id)
            return True
        except Exception:
            continue
    return False


def _get_attr(obj: Any, names: List[str], default=None):
    if obj is None:
        return default

    # Support dict-shaped objects (some instagrapi endpoints/fallbacks return dicts).
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                v = obj.get(n)
                if v is not None:
                    return v
        return default

    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default


def _pending_threads_via_private_request(client: Any, limit: int) -> List[Any]:
    """Fallback: fetch pending inbox via raw private_request and return thread stubs."""
    if not hasattr(client, 'private_request'):
        return []

    limit = int(limit or 10)
    resp = None
    last_err = None

    # Different instagrapi versions accept different signatures.
    try_variants = [
        ('direct_v2/pending_inbox/', {'limit': limit}),
        ('direct_v2/pending_inbox/', {}),
    ]

    for endpoint, params in try_variants:
        try:
            try:
                resp = client.private_request(endpoint, params=params)
            except TypeError:
                resp = client.private_request(endpoint)
            if resp is not None:
                break
        except Exception as e:
            last_err = e
            resp = None

    if resp is None:
        if last_err is not None:
            raise last_err
        return []

    if not isinstance(resp, dict):
        return []

    inbox = resp.get('inbox') if isinstance(resp.get('inbox'), dict) else resp
    if not isinstance(inbox, dict):
        return []

    threads = inbox.get('threads') or []
    if not isinstance(threads, list):
        return []

    stubs: List[Dict[str, str]] = []
    for th in threads[: max(1, limit)]:
        if not isinstance(th, dict):
            continue
        tid = str(th.get('thread_id') or th.get('id') or '')
        if not tid:
            continue
        stubs.append({'thread_id': tid, 'id': tid})
    return stubs


def _items_from_private_thread_resp(resp: Any) -> List[Any]:
    """Extract message items from a private_request thread response."""
    if resp is None:
        return []
    if not isinstance(resp, dict):
        return []

    # Shapes observed in IG private API:
    # - {"thread": {"items": [...]}}
    # - {"items": [...]} (rare)
    thread = resp.get('thread') if isinstance(resp.get('thread'), dict) else None
    if thread is not None:
        items = thread.get('items') or []
        return items if isinstance(items, list) else []

    items = resp.get('items') or []
    return items if isinstance(items, list) else []


def _get_messages_best_effort(client: Any, thread_id: str, amount: int) -> List[Any]:
    """Try instagrapi direct_messages(), then fall back to raw private_request."""
    amount = int(amount or 20)

    # 1) Primary: instagrapi
    if hasattr(client, 'direct_messages'):
        try:
            return client.direct_messages(thread_id, amount=amount)
        except Exception as e:
            _debug(f"DM assistant: thread={thread_id} direct_messages_failed: {e}")

    # 2) Fallback: private request
    if hasattr(client, 'private_request'):
        last_err = None
        endpoints = [
            (f'direct_v2/threads/{thread_id}/', {'limit': amount}),
            (f'direct_v2/threads/{thread_id}/', {}),
        ]
        for endpoint, params in endpoints:
            try:
                try:
                    resp = client.private_request(endpoint, params=params)
                except TypeError:
                    resp = client.private_request(endpoint)
                items = _items_from_private_thread_resp(resp)
                if items is not None:
                    return items
            except Exception as e:
                last_err = e
                continue
        if last_err is not None:
            _debug(f"DM assistant: thread={thread_id} private_thread_failed: {last_err}")

    return []


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
        threads = _get_threads_best_effort(client, int(threads_limit or 10))
    except Exception as e:
        settings.last_error = f'direct_threads_failed: {e}'
        return 0

    _debug(f"DM assistant: account=@{account.instagram_username} inbox_threads={len(threads or [])}")

    # Also try to include message requests (pending inbox).
    # Many new accounts receive first-time DMs as "requests", which are not
    # returned by direct_threads(). We do best-effort introspection here to
    # support multiple instagrapi versions.
    pending_ids = set()

    pending_threads: List[Any] = []
    pending_obj = None
    pending_err = None

    if hasattr(client, 'direct_pending_inbox'):
        try:
            try:
                pending_obj = client.direct_pending_inbox(amount=int(threads_limit or 10))
            except TypeError:
                pending_obj = client.direct_pending_inbox()
        except Exception as e:
            pending_err = e
    elif hasattr(client, 'direct_pending_inbox_v1'):
        try:
            try:
                pending_obj = client.direct_pending_inbox_v1(amount=int(threads_limit or 10))
            except TypeError:
                pending_obj = client.direct_pending_inbox_v1()
        except Exception as e:
            pending_err = e

    if pending_err is not None:
        _debug(f"DM assistant: account=@{account.instagram_username} pending_inbox_failed: {pending_err}")

    pending_threads = _extract_threads_from_inbox_obj(pending_obj)
    if not pending_threads:
        try:
            pending_threads = _pending_threads_via_private_request(client, int(threads_limit or 10))
            if pending_threads:
                _debug(f"DM assistant: account=@{account.instagram_username} pending_threads_added_via_private={len(pending_threads)}")
        except Exception as e:
            _debug(f"DM assistant: account=@{account.instagram_username} pending_private_failed: {e}")

    if pending_threads:
        # De-duplicate by thread_id
        seen_ids = set()
        merged = []
        for th in (threads or []):
            tid = str(_get_attr(th, ['id', 'thread_id', 'pk'], default=''))
            if not tid or tid in seen_ids:
                continue
            seen_ids.add(tid)
            merged.append(th)
        for th in pending_threads:
            tid = str(_get_attr(th, ['id', 'thread_id', 'pk'], default=''))
            if not tid or tid in seen_ids:
                continue
            seen_ids.add(tid)
            pending_ids.add(tid)
            merged.append(th)
        threads = merged
        _debug(f"DM assistant: account=@{account.instagram_username} pending_threads_added={len(pending_threads)} total_threads={len(threads)}")
    for th in threads:
        if daily_sent + replied_count >= daily_cap:
            break

        thread_id = str(_get_attr(th, ['id', 'thread_id', 'pk'], default=''))
        if not thread_id:
            continue

        is_pending_thread = thread_id in pending_ids

        state = DmThreadState.query.filter_by(instagram_account_id=account_id, thread_id=thread_id).first()

        msgs = _get_messages_best_effort(client, thread_id, int(messages_per_thread or 20))
        if not msgs:
            _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} msgs=0 pending={is_pending_thread}")
            continue

        # Ensure chronological order
        msgs_sorted = sorted(msgs, key=lambda m: (_get_attr(m, ['timestamp', 'created_at', 'time'], default=0) or 0))
        newest = msgs_sorted[-1]
        newest_id = str(_get_attr(newest, ['id', 'item_id', 'pk', 'uuid'], default=''))

        # Always persist a small window for debugging/context even if we skip replying.
        _persist_messages_best_effort(
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id,
            messages=msgs_sorted,
            my_user_id=my_user_id,
            max_items=12,
        )

        if state is None:
            state = DmThreadState(user_id=user_id, instagram_account_id=account_id, thread_id=thread_id)
            db.session.add(state)

            newest_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            newest_sender_id = str(_get_attr(newest, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
            newest_text = (_get_attr(newest, ['text', 'message', 'content'], default='') or '').strip()

            is_newest_inbound = bool(newest_text) and not (my_user_id and newest_sender_id == my_user_id)
            is_recent = bool(newest_at and newest_at >= (_now_utc() - timedelta(minutes=FIRST_SEEN_REPLY_WINDOW_MINUTES)))
            # If timestamp is missing/unsupported, treat pending inbox as "recent" to avoid silent skips.
            if newest_at is None and is_pending_thread and is_newest_inbound:
                is_recent = True

            # Pending/message-request inbox is a special case: if the latest message is inbound,
            # we allow a first reply even if it's older than the recency window.
            if is_pending_thread and is_newest_inbound:
                is_recent = True

            # First time we see a thread:
            # - If reply_to_existing_threads is enabled, allow replying immediately.
            # - Otherwise only reply if the latest inbound message is recent.
            if settings.reply_to_existing_threads or (is_newest_inbound and is_recent):
                # Empty cursor means "treat newest as new".
                state.last_seen_item_id = ''
                state.last_seen_at = newest_at
                db.session.commit()
            else:
                # Default safe behavior: move cursor to newest and do not reply.
                state.last_seen_item_id = newest_id
                state.last_seen_at = newest_at
                db.session.commit()
                _debug(
                    f"DM assistant: account=@{account.instagram_username} thread={thread_id} first_seen_skip "
                    f"reply_to_existing={bool(settings.reply_to_existing_threads)} newest_inbound={is_newest_inbound} "
                    f"recent={is_recent} pending={is_pending_thread} newest_at={bool(newest_at)}"
                )
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

        if _is_debug() and not inbound and new_msgs:
            from_me = 0
            no_text = 0
            other_with_text = 0
            samples = []
            for m in new_msgs[:3]:
                sender_id = str(_get_attr(m, ['user_id', 'sender_id', 'from_user_id'], default='') or '')
                is_me = bool(my_user_id and sender_id == my_user_id)
                if is_me:
                    from_me += 1
                text = (_get_attr(m, ['text', 'message', 'content'], default='') or '').strip()
                if not text:
                    no_text += 1
                else:
                    if not is_me:
                        other_with_text += 1
                item_type = str(_get_attr(m, ['item_type', 'type'], default='') or '')
                samples.append(
                    f"type={item_type or '?'} is_me={is_me} sender={sender_id or '?'} text={(text[:30] + '…') if len(text) > 30 else text}"
                )

            _debug(
                f"DM assistant: account=@{account.instagram_username} thread={thread_id} "
                f"no_inbound_text new_msgs={len(new_msgs)} pending={is_pending_thread} "
                f"from_me={from_me} no_text={no_text} other_with_text={other_with_text} sample=[{'; '.join(samples)}]"
            )

        # For pending threads, it's common that the cursor got advanced earlier (safe-skip)
        # but we still want to send a one-time reply to the latest unprocessed inbound.
        pending_in_row = None
        if (not inbound) and is_pending_thread:
            pending_in_row = (DmMessage.query
                              .filter_by(instagram_account_id=account_id, thread_id=thread_id, direction='in', processed=False)
                              .order_by(DmMessage.created_at.desc())
                              .first())

        if not inbound and pending_in_row is None:
            # Update cursor to newest to avoid re-processing
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            continue

        last_in = inbound[-1] if inbound else None

        # Persist only-new messages too (already persisted full window above, but keep this cheap).
        _persist_messages_best_effort(
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id,
            messages=new_msgs,
            my_user_id=my_user_id,
            max_items=12,
        )

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
            _debug(
                f"DM assistant: account=@{account.instagram_username} thread={thread_id} empty_reply pending={is_pending_thread}"
            )
            state.last_seen_item_id = newest_id
            state.last_seen_at = _as_datetime(_get_attr(newest, ['timestamp', 'created_at', 'time'], default=None))
            db.session.commit()
            continue

        # Send
        try:
            _debug(
                f"DM assistant: account=@{account.instagram_username} thread={thread_id} "
                f"sending_reply chars={len(reply_text)} pending={is_pending_thread}"
            )
            _debug(f"DM assistant: reply_text_preview: {reply_text[:100]}...")
            
            approved = False
            if is_pending_thread and _auto_approve_requests():
                approved = _try_approve_thread(client, thread_id)
                _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} approve_attempt={approved}")

            result = None
            send_err = None

            # Try direct_send first (standard method)
            if hasattr(client, 'direct_send'):
                try:
                    result = client.direct_send(reply_text, thread_ids=[thread_id])
                    _debug(f"DM assistant: direct_send returned: {type(result)} = {result}")
                except Exception as e:
                    send_err = e
                    _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} direct_send_err: {e}")

            # Fallback: private_request to messages endpoint
            if result is None and hasattr(client, 'private_request'):
                try:
                    payload = {
                        'thread_ids': f'[{thread_id}]',
                        'text': reply_text,
                        'action': 'send_item',
                    }
                    resp = client.private_request('direct_v2/threads/broadcast/text/', data=payload)
                    _debug(f"DM assistant: private_request broadcast returned: {resp}")
                    if resp:
                        result = resp
                        send_err = None
                        _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} sent_via_private_request")
                except Exception as e2:
                    if send_err is None:
                        send_err = e2
                    _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} private_send_err: {e2}")

            if result is None and send_err is not None:
                raise send_err

            # Log result details for debugging
            result_id = str(_get_attr(result, ['id', 'item_id', 'pk', 'uuid', 'message_id'], default='') or '')
            _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} sent_ok result_id={result_id}")
        except Exception as e:
            settings.last_error = f'direct_send_failed(thread={thread_id}): {e}'
            _debug(f"DM assistant: account=@{account.instagram_username} thread={thread_id} send_failed: {e}")
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
        in_item_id = ''
        if last_in is not None:
            in_item_id = str(_get_attr(last_in, ['id', 'item_id', 'pk', 'uuid'], default=''))
        elif pending_in_row is not None:
            in_item_id = str(pending_in_row.item_id or '')
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
