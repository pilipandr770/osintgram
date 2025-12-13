"""Add animation/music columns to automation_settings (idempotent).

Run:
  py -3.10 migrate_automation_v3.py
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

print('Altering automation_settings (v3)...')

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
    ALTER TABLE osintgram.automation_settings
    ADD COLUMN IF NOT EXISTS music_file_path TEXT;
""")
cur.execute("""
    ALTER TABLE osintgram.automation_settings
    ADD COLUMN IF NOT EXISTS animation_duration_seconds INTEGER;
""")
cur.execute("""
    ALTER TABLE osintgram.automation_settings
    ADD COLUMN IF NOT EXISTS animation_fps INTEGER;
""")

cur.close()
conn.close()

print('Done.')
