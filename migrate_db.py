"""
Скрипт міграції бази даних.
Додає нові колонки для геолокації та інтересів.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL не знайдено в .env")
    exit(1)

# Виправляємо для SQLAlchemy 2.x
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(DATABASE_URL)

# SQL для додавання нових колонок
migration_sql = """
-- Додаємо колонки геолокації
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS detected_city VARCHAR(100);
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS detected_country VARCHAR(100);
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS location_confidence VARCHAR(20);
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS is_frankfurt_region BOOLEAN DEFAULT FALSE;

-- Додаємо колонки інтересів
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS matched_keywords JSON;
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS interest_score INTEGER DEFAULT 0;
ALTER TABLE osintgram.followers ADD COLUMN IF NOT EXISTS is_target_audience BOOLEAN DEFAULT FALSE;

-- Створюємо індекси для швидкого пошуку
CREATE INDEX IF NOT EXISTS idx_followers_detected_city ON osintgram.followers(detected_city);
CREATE INDEX IF NOT EXISTS idx_followers_is_frankfurt_region ON osintgram.followers(is_frankfurt_region);
CREATE INDEX IF NOT EXISTS idx_followers_is_target_audience ON osintgram.followers(is_target_audience);
"""

print("🔄 Запуск міграції бази даних...")

try:
    with engine.connect() as conn:
        # Виконуємо кожну команду окремо
        for statement in migration_sql.strip().split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    conn.execute(text(statement))
                    print(f"✅ {statement[:60]}...")
                except Exception as e:
                    # Ігноруємо помилки "вже існує"
                    if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                        print(f"⏭️ Пропускаємо (вже існує): {statement[:40]}...")
                    else:
                        print(f"⚠️ Помилка: {e}")
        
        conn.commit()
    
    print("\n✅ Міграція завершена успішно!")
    print("🔄 Перезапустіть додаток: py -3.10 app.py")

except Exception as e:
    print(f"❌ Помилка міграції: {e}")
