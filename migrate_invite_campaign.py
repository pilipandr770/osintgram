"""Create invite campaign tables (idempotent).

Run:
  py -3.10 migrate_invite_campaign.py

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

print('Creating invite campaign tables...')

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.invite_campaign_settings (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  enabled BOOLEAN DEFAULT FALSE,
  audience_type VARCHAR(50) DEFAULT 'target',
  max_sends_per_day INTEGER DEFAULT 20,
  min_delay_seconds INTEGER DEFAULT 45,
  max_delay_seconds INTEGER DEFAULT 75,
  steps JSON,
  stop_on_inbound_reply BOOLEAN DEFAULT TRUE,
  last_run_at TIMESTAMP,
  last_error TEXT,
  created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
  updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_campaign_settings_user_account
ON osintgram.invite_campaign_settings (user_id, instagram_account_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_invite_campaign_settings_user
ON osintgram.invite_campaign_settings (user_id);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.invite_campaign_recipients (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  recipient_username VARCHAR(255) NOT NULL,
  recipient_user_id VARCHAR(255),
  status VARCHAR(32) DEFAULT 'active',
  current_step INTEGER DEFAULT 0,
  thread_id VARCHAR(128),
  last_outbound_at TIMESTAMP,
  last_inbound_at TIMESTAMP,
  enrolled_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
  next_send_at TIMESTAMP,
  completed_at TIMESTAMP,
  last_error TEXT,
  created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
  updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_campaign_rec_unique
ON osintgram.invite_campaign_recipients (instagram_account_id, recipient_username);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_invite_campaign_rec_due
ON osintgram.invite_campaign_recipients (next_send_at);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_invite_campaign_rec_status
ON osintgram.invite_campaign_recipients (status);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS osintgram.invite_campaign_sends (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
  instagram_account_id VARCHAR(36) NOT NULL REFERENCES osintgram.instagram_accounts(id),
  recipient_username VARCHAR(255) NOT NULL,
  recipient_user_id VARCHAR(255),
  thread_id VARCHAR(128),
  step_index INTEGER NOT NULL,
  message_text TEXT,
  status VARCHAR(32) DEFAULT 'sent',
  error_message TEXT,
  sent_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_invite_campaign_send_account
ON osintgram.invite_campaign_sends (instagram_account_id);
""")
cur.execute("""
CREATE INDEX IF NOT EXISTS idx_invite_campaign_send_recipient
ON osintgram.invite_campaign_sends (instagram_account_id, recipient_username);
""")

cur.close()
conn.close()

print('Done.')
