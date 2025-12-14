"""Run invite campaign loop: periodically send scheduled invite DMs.

Usage:
  py -3.10 invite_campaign_runner.py

Enable/disable via env:
  ENABLE_INVITE_CAMPAIGN=true
  INVITE_CAMPAIGN_LOOP_SECONDS=60

Notes:
- Run as a separate worker process.
- Avoid running multiple workers to reduce duplicate sends.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ENABLE_INVITE_CAMPAIGN = os.environ.get('ENABLE_INVITE_CAMPAIGN', 'false').lower() in {'1', 'true', 'yes'}
LOOP_SECONDS = int(os.environ.get('INVITE_CAMPAIGN_LOOP_SECONDS', '60'))

# Import the app to initialize db
import app as app_module  # noqa: E402
from models import User  # noqa: E402
from invite_campaign_service import run_invite_campaign_for_user  # noqa: E402


def main():
    if not ENABLE_INVITE_CAMPAIGN:
        print('Invite campaign disabled (set ENABLE_INVITE_CAMPAIGN=true).')
        raise SystemExit(0)

    flask_app = app_module.create_app()

    with flask_app.app_context():
        while True:
            try:
                users = User.query.all()
                for u in users:
                    stats = run_invite_campaign_for_user(u.id)
                    if stats.get('sent') or stats.get('stopped') or stats.get('completed') or stats.get('failed'):
                        print(f"[{datetime.utcnow().isoformat()}] user={u.id} {stats}")
            except Exception as e:
                print(f"Invite campaign error: {e}")

            time.sleep(max(10, LOOP_SECONDS))


if __name__ == '__main__':
    main()
