"""Create geo_settings table (per-user configurable geo targeting).

Usage:
  py -3.10 migrate_geo_settings.py

This project also runs db.create_all() on startup, but this script is useful
for existing DBs / Render deployments.
"""

from dotenv import load_dotenv

load_dotenv()

from app import app  # noqa: E402
from database import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from database import SCHEMA_NAME  # noqa: E402


def main() -> None:
    with app.app_context():
        print('Migrating geo_settings...')
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.geo_settings (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            region_name VARCHAR(120) DEFAULT 'Frankfurt',
            radius_km INTEGER DEFAULT 100,
            region_cities JSON,
            postal_code_regex VARCHAR(160),
            priority_hashtags JSON,
            suggested_keywords JSON,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT fk_geo_settings_user FOREIGN KEY(user_id) REFERENCES {SCHEMA_NAME}.users(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_settings_user ON {SCHEMA_NAME}.geo_settings(user_id);
        """
        db.session.execute(text(ddl))
        db.session.commit()
        print('Done.')


if __name__ == '__main__':
    main()
