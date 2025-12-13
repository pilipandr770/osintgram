"""
Примусове додавання колонок - виконується окремо від Flask
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("❌ DATABASE_URL не знайдено")
    exit(1)

# Конвертуємо URL для psycopg2
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

print("🔗 Підключення до бази даних...")
print(f"📍 URL: {DATABASE_URL[:50]}...")

try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    print("\n🔍 Перевіряємо існуючі колонки...")
    cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_schema = 'osintgram' AND table_name = 'followers'
    """)
    existing = [row[0] for row in cursor.fetchall()]
    print(f"📋 Знайдено {len(existing)} колонок: {existing[:10]}...")
    
    # Колонки які потрібно додати
    columns_to_add = [
        ("detected_city", "VARCHAR(100)"),
        ("detected_country", "VARCHAR(100)"),
        ("location_confidence", "VARCHAR(20)"),
        ("is_frankfurt_region", "BOOLEAN DEFAULT FALSE"),
        ("matched_keywords", "JSON"),
        ("interest_score", "INTEGER DEFAULT 0"),
        ("is_target_audience", "BOOLEAN DEFAULT FALSE"),
    ]
    
    print("\n🔧 Додаємо відсутні колонки...")
    for col_name, col_type in columns_to_add:
        if col_name not in existing:
            try:
                sql = f"ALTER TABLE osintgram.followers ADD COLUMN {col_name} {col_type}"
                cursor.execute(sql)
                print(f"  ✅ Додано: {col_name}")
            except Exception as e:
                if 'already exists' in str(e).lower():
                    print(f"  ⏭️ Вже існує: {col_name}")
                else:
                    print(f"  ❌ Помилка {col_name}: {e}")
        else:
            print(f"  ⏭️ Вже існує: {col_name}")
    
    # Перевіряємо результат
    print("\n🔍 Фінальна перевірка...")
    cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_schema = 'osintgram' AND table_name = 'followers'
        ORDER BY ordinal_position
    """)
    final_columns = [row[0] for row in cursor.fetchall()]
    print(f"📋 Всього колонок: {len(final_columns)}")
    
    # Перевіряємо нові колонки
    new_cols = ['detected_city', 'detected_country', 'location_confidence', 
                'is_frankfurt_region', 'matched_keywords', 'interest_score', 'is_target_audience']
    missing = [c for c in new_cols if c not in final_columns]
    
    if missing:
        print(f"❌ Відсутні колонки: {missing}")
    else:
        print("✅ ВСІ НОВІ КОЛОНКИ ДОДАНІ УСПІШНО!")
    
    cursor.close()
    conn.close()
    print("\n🎉 Готово! Тепер перезапустіть app.py")
    
except Exception as e:
    print(f"❌ Помилка підключення: {e}")
