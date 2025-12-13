"""
Міграція: таблиці для автоматизації та кешу AI (щоб не зберігати великі дані у cookie-session).
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL is not set')

print('Creating automation_settings and ai_cache...')

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS osintgram.automation_settings (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
        enabled BOOLEAN DEFAULT FALSE,
        rss_check_interval_minutes INTEGER DEFAULT 240,
        publish_times JSON,
        timezone VARCHAR(64) DEFAULT 'Europe/Berlin',
        max_posts_per_day INTEGER DEFAULT 2,
        auto_publish BOOLEAN DEFAULT FALSE,
        use_animation BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_settings_user
    ON osintgram.automation_settings(user_id);
""")

cur.execute("""
    CREATE TABLE IF NOT EXISTS osintgram.ai_cache (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
        kind VARCHAR(50) NOT NULL,
        payload JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_ai_cache_user_kind
    ON osintgram.ai_cache(user_id, kind);
""")

cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_ai_cache_created
    ON osintgram.ai_cache(created_at);
""")

cur.close()
conn.close()

print('Done.')
