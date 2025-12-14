"""Run all background workers in a single process.

This is a convenience runner for local/dev usage.

Usage:
  py -3.10 all_workers_runner.py

Enable via env:
  ENABLE_ALL_WORKERS=true
  WORKERS_LOOP_SECONDS=60

Behavior:
- Automation: runs only when AutomationSettings.enabled=true (UI-controlled).
- DM assistant: runs only for accounts with DmAssistantSettings.enabled=true (UI-controlled).
- Invite campaign: runs only for accounts with InviteCampaignSettings.enabled=true (UI-controlled).

Notes:
- For production, prefer separate worker processes.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ENABLE_ALL_WORKERS = os.environ.get('ENABLE_ALL_WORKERS', 'false').lower() in {'1', 'true', 'yes'}
LOOP_SECONDS = int(os.environ.get('WORKERS_LOOP_SECONDS', '60'))


def main():
    if not ENABLE_ALL_WORKERS:
        print('All workers runner disabled (set ENABLE_ALL_WORKERS=true).')
        raise SystemExit(0)

    # Import only when enabled to avoid side effects on import.
    import app as app_module  # noqa: E402
    from models import User  # noqa: E402
    from dm_assistant_service import poll_and_reply_for_user  # noqa: E402
    from invite_campaign_service import run_invite_campaign_for_user  # noqa: E402
    from automation_service import create_scheduled_content_from_new_rss, publish_due_content  # noqa: E402

    # Reuse the app instance created in app.py (prevents double create_app()).
    flask_app = getattr(app_module, 'app', None) or app_module.create_app()

    with flask_app.app_context():
        while True:
            try:
                users = User.query.all()
                for u in users:
                    created = create_scheduled_content_from_new_rss(u.id, days=2, max_topics=20)
                    published = publish_due_content(u.id, limit=3)
                    replied = poll_and_reply_for_user(u.id, threads_limit=10, messages_per_thread=20)
                    stats = run_invite_campaign_for_user(u.id)

                    if created or published or replied or stats.get('sent') or stats.get('stopped') or stats.get('failed'):
                        print(
                            f"[{datetime.utcnow().isoformat()}] user={u.id} "
                            f"automation(created={created}, published={published}) "
                            f"dm_replied={replied} invite={stats}"
                        )
            except Exception as e:
                print(f"All workers error: {e}")

            time.sleep(max(10, LOOP_SECONDS))


if __name__ == '__main__':
    main()
