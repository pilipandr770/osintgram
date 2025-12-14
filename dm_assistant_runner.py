"""Run DM assistant loop: periodically check Instagram Direct inbox and auto-reply.

Usage:
  py -3.10 dm_assistant_runner.py

Enable/disable via env:
  ENABLE_DM_ASSISTANT=true
  DM_ASSISTANT_LOOP_SECONDS=45

Notes:
- Run as a separate worker process.
- Keep the web app process free from background loops to avoid duplicates.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ENABLE_DM_ASSISTANT = os.environ.get('ENABLE_DM_ASSISTANT', 'false').lower() in {'1', 'true', 'yes'}
LOOP_SECONDS = int(os.environ.get('DM_ASSISTANT_LOOP_SECONDS', '45'))

if not ENABLE_DM_ASSISTANT:
    print('DM assistant disabled (set ENABLE_DM_ASSISTANT=true).')
    raise SystemExit(0)

import app as app_module  # noqa: E402
from models import User  # noqa: E402
from dm_assistant_service import poll_and_reply_for_user  # noqa: E402


def main():
    flask_app = app_module.create_app()

    with flask_app.app_context():
        while True:
            try:
                users = User.query.all()
                total = 0
                for u in users:
                    total += poll_and_reply_for_user(u.id, threads_limit=10, messages_per_thread=20)
                if total:
                    print(f"[{datetime.utcnow().isoformat()}] dm replies sent: {total}")
            except Exception as e:
                print(f"DM assistant error: {e}")

            time.sleep(max(10, LOOP_SECONDS))


if __name__ == '__main__':
    main()
