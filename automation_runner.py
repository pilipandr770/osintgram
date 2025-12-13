"""Run automation loop: periodically fetch RSS, create scheduled drafts, and publish due posts.

Usage:
  py -3.10 automation_runner.py

Enable/disable via env:
  ENABLE_AUTOMATION=true
  AUTOMATION_LOOP_SECONDS=60

Notes:
- For production (Render), run this as a separate worker process.
- The web app process should generally NOT run the scheduler to avoid duplicates.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ENABLE_AUTOMATION = os.environ.get('ENABLE_AUTOMATION', 'false').lower() in {'1', 'true', 'yes'}
LOOP_SECONDS = int(os.environ.get('AUTOMATION_LOOP_SECONDS', '60'))

if not ENABLE_AUTOMATION:
    print('Automation disabled (set ENABLE_AUTOMATION=true).')
    raise SystemExit(0)

# Import the app to initialize db
import app as app_module  # noqa: E402
from database import db  # noqa: E402
from models import User  # noqa: E402
from automation_service import create_scheduled_content_from_new_rss, publish_due_content  # noqa: E402


def main():
    flask_app = app_module.create_app()

    with flask_app.app_context():
        while True:
            try:
                users = User.query.all()
                for u in users:
                    created = create_scheduled_content_from_new_rss(u.id, days=2, max_topics=20)
                    published = publish_due_content(u.id, limit=3)
                    if created or published:
                        print(f"[{datetime.utcnow().isoformat()}] user={u.id} created={created} published={published}")
            except Exception as e:
                print(f"Automation error: {e}")

            time.sleep(max(10, LOOP_SECONDS))


if __name__ == '__main__':
    main()
