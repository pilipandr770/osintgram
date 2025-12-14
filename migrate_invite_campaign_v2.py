"""Add quiet-hours (day/night) fields to invite campaign settings (idempotent).

Run:
  py -3.10 migrate_invite_campaign_v2.py

Requires DATABASE_URL.
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

print('Migrating invite_campaign_settings: add allowed hours + timezone...')

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
ALTER TABLE IF EXISTS osintgram.invite_campaign_settings
  ADD COLUMN IF NOT EXISTS allowed_start_hour INTEGER DEFAULT 8;
""")
cur.execute("""
ALTER TABLE IF EXISTS osintgram.invite_campaign_settings
  ADD COLUMN IF NOT EXISTS allowed_end_hour INTEGER DEFAULT 22;
""")
cur.execute("""
ALTER TABLE IF EXISTS osintgram.invite_campaign_settings
  ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'Europe/Berlin';
""")

# Backfill NULLs
cur.execute("""
UPDATE osintgram.invite_campaign_settings
SET allowed_start_hour = COALESCE(allowed_start_hour, 8),
    allowed_end_hour = COALESCE(allowed_end_hour, 22),
    timezone = COALESCE(timezone, 'Europe/Berlin')
WHERE allowed_start_hour IS NULL OR allowed_end_hour IS NULL OR timezone IS NULL;
""")

cur.close()
conn.close()

print('Done.')
