"""Run web app + all background workers with one command.

Usage (local/dev):
  py -3.10 run_all.py

Notes:
- Runs Flask dev server (without the reloader) and a background workers loop in a daemon thread.
- Worker behavior is still UI-controlled (AutomationSettings/DmAssistantSettings/InviteCampaignSettings).
- For production, run web and workers as separate processes.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5000'))
WORKERS_LOOP_SECONDS = int(os.environ.get('WORKERS_LOOP_SECONDS', '60'))

# Start workers by default in this entrypoint; can be disabled explicitly.
ENABLE_WORKERS = os.environ.get('ENABLE_ALL_WORKERS', 'true').lower() in {'1', 'true', 'yes'}


def _workers_loop(flask_app) -> None:
    """Background loop that runs automation + dm assistant + invite campaign."""
    if not ENABLE_WORKERS:
        print('Workers disabled (set ENABLE_ALL_WORKERS=true to enable).')
        return

    from models import User  # imported after dotenv
    from dm_assistant_service import poll_and_reply_for_user
    from invite_campaign_service import run_invite_campaign_for_user
    from automation_service import create_scheduled_content_from_new_rss, publish_due_content

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

            time.sleep(max(10, WORKERS_LOOP_SECONDS))


def main() -> None:
    import app as app_module
    from database import init_db

    flask_app = getattr(app_module, 'app', None) or app_module.create_app()

    # Initialize DB connection for local runs (same as app.py __main__).
    init_db(flask_app)

    # Ensure uploads dir exists
    os.makedirs(flask_app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)

    t = threading.Thread(target=_workers_loop, args=(flask_app,), daemon=True)
    t.start()

    print('Starting web + workers...')
    print(f"Web: http://127.0.0.1:{PORT}")
    print('Workers: running in background thread')

    # IMPORTANT: disable reloader to avoid starting workers twice.
    flask_app.run(host=HOST, port=PORT, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
