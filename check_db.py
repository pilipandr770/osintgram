"""
Перевірка структури таблиці followers
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(DATABASE_URL)

print("🔍 Перевіряємо структуру таблиці followers...")

with engine.connect() as conn:
    # Перевіряємо які колонки існують
    result = conn.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'osintgram' 
        AND table_name = 'followers'
        ORDER BY ordinal_position;
    """))
    
    print("\n📋 Колонки таблиці osintgram.followers:")
    print("-" * 50)
    columns = []
    for row in result:
        print(f"  {row[0]:30} | {row[1]}")
        columns.append(row[0])
    
    # Перевіряємо чи є нові колонки
    new_columns = ['detected_city', 'detected_country', 'location_confidence', 
                   'is_frankfurt_region', 'matched_keywords', 'interest_score', 'is_target_audience']
    
    print("\n🔎 Статус нових колонок:")
    for col in new_columns:
        status = "✅" if col in columns else "❌"
        print(f"  {status} {col}")
