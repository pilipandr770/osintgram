"""
Міграція: створення таблиць для розсилки повідомлень
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

print("🔄 Створення таблиць для розсилки повідомлень...")

try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Таблиця логів розсилок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS osintgram.message_logs (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
            account_id VARCHAR(36) REFERENCES osintgram.instagram_accounts(id),
            account_username VARCHAR(255),
            total_sent INTEGER DEFAULT 0,
            successful INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            message_template TEXT,
            audience_type VARCHAR(50),
            status VARCHAR(50) DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    print("  ✅ Таблиця message_logs створена")
    
    # Таблиця відправлених повідомлень
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS osintgram.sent_messages (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES osintgram.users(id),
            message_log_id VARCHAR(36) REFERENCES osintgram.message_logs(id),
            recipient_username VARCHAR(255) NOT NULL,
            recipient_user_id VARCHAR(255),
            status VARCHAR(50) DEFAULT 'sent',
            error_message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✅ Таблиця sent_messages створена")
    
    # Індекси
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_message_logs_user_id ON osintgram.message_logs(user_id);
        CREATE INDEX IF NOT EXISTS idx_message_logs_created_at ON osintgram.message_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_sent_messages_user_id ON osintgram.sent_messages(user_id);
        CREATE INDEX IF NOT EXISTS idx_sent_messages_recipient ON osintgram.sent_messages(recipient_username);
        CREATE INDEX IF NOT EXISTS idx_sent_messages_sent_at ON osintgram.sent_messages(sent_at);
    """)
    print("  ✅ Індекси створені")
    
    cursor.close()
    conn.close()
    
    print("\n✅ Міграція завершена успішно!")
    print("🚀 Тепер можна перезапустити app.py")
    
except Exception as e:
    print(f"❌ Помилка: {e}")
