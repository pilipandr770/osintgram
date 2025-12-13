"""Очистка бази від невалідних записів"""
import os
import psycopg2
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

# Видаляємо сміття - записи де username містить JSON або спецсимволи
cursor.execute("""
    DELETE FROM osintgram.followers 
    WHERE username LIKE '%"%' 
       OR username LIKE '%{%' 
       OR username LIKE '%}%'
       OR username LIKE '%:%'
       OR username LIKE '% %'
       OR LENGTH(username) > 30
""")
deleted = cursor.rowcount
print(f'🗑️ Видалено {deleted} невалідних записів')

# Перевіряємо що залишилось
cursor.execute('SELECT COUNT(*) FROM osintgram.followers')
remaining = cursor.fetchone()[0]
print(f'✅ Залишилось {remaining} валідних підписчиків')

# Показуємо приклади
cursor.execute('SELECT username FROM osintgram.followers LIMIT 10')
print('\n📋 Приклади username:')
for row in cursor.fetchall():
    print(f'   @{row[0]}')

cursor.close()
conn.close()
