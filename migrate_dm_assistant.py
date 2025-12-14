"""Create DM assistant tables (idempotent).

Run:
  py -3.10 migrate_dm_assistant.py

Requires DATABASE_URL in environment.
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

print('Creating dm assistant tables...')

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.dm_assistant_settings (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  enabled BOOLEAN DEFAULT FALSE,
  system_instructions TEXT,
  language VARCHAR(16) DEFAULT 'ru',
  max_replies_per_day INTEGER DEFAULT 20,
  min_delay_seconds INTEGER DEFAULT 15,
  max_delay_seconds INTEGER DEFAULT 45,
  reply_to_existing_threads BOOLEAN DEFAULT FALSE,
  last_run_at TIMESTAMP,
  last_error TEXT,
  created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
  updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")

cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_dm_assistant_settings_user_account
ON osintgram.dm_assistant_settings (user_id, instagram_account_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_dm_assistant_settings_user
ON osintgram.dm_assistant_settings (user_id);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.dm_thread_state (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  thread_id VARCHAR(128) NOT NULL,
  last_seen_item_id VARCHAR(128),
  last_seen_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
  updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_dm_thread_state_thread
ON osintgram.dm_thread_state (instagram_account_id, thread_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_dm_thread_state_user_account
ON osintgram.dm_thread_state (user_id, instagram_account_id);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.dm_messages (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  thread_id VARCHAR(128) NOT NULL,
  item_id VARCHAR(128) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  sender_user_id VARCHAR(128),
  sender_username VARCHAR(255),
  text TEXT,
  sent_at TIMESTAMP,
  processed BOOLEAN DEFAULT FALSE,
  reply_text TEXT,
  replied_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_dm_messages_item
ON osintgram.dm_messages (instagram_account_id, thread_id, item_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_dm_messages_thread
ON osintgram.dm_messages (instagram_account_id, thread_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_dm_messages_user
ON osintgram.dm_messages (user_id);
""")

cur.close()
conn.close()

print('Done.')
