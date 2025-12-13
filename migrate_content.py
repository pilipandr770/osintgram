"""
Міграція: таблиця для трендів та контент-ідей
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

print("🔄 Створення таблиць для контенту та трендів...")

try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Таблиця трендів з RSS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS osintgram.rss_trends (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) REFERENCES osintgram.users(id),
            title VARCHAR(500) NOT NULL,
            content TEXT,
            link VARCHAR(1000),
            source VARCHAR(100),
            category VARCHAR(50),
            language VARCHAR(10),
            image_url VARCHAR(1000),
            matched_keywords JSON,
            relevance_score INTEGER DEFAULT 0,
            published_at TIMESTAMP,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✅ Таблиця rss_trends створена")
    
    # Таблиця ідей контенту
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS osintgram.content_ideas (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) REFERENCES osintgram.users(id),
            trend_id VARCHAR(36) REFERENCES osintgram.rss_trends(id),
            title VARCHAR(500),
            caption TEXT,
            hashtags JSON,
            content_type VARCHAR(50),
            image_prompt TEXT,
            generated_image_url VARCHAR(1000),
            video_url VARCHAR(1000),
            status VARCHAR(50) DEFAULT 'draft',
            scheduled_at TIMESTAMP,
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✅ Таблиця content_ideas створена")
    
    # Таблиця для згенерованих медіа
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS osintgram.generated_media (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) REFERENCES osintgram.users(id),
            content_idea_id VARCHAR(36) REFERENCES osintgram.content_ideas(id),
            media_type VARCHAR(50),
            prompt TEXT,
            provider VARCHAR(50),
            source_url VARCHAR(1000),
            local_path VARCHAR(500),
            thumbnail_url VARCHAR(1000),
            width INTEGER,
            height INTEGER,
            duration_seconds INTEGER,
            status VARCHAR(50) DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✅ Таблиця generated_media створена")
    
    # Індекси
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rss_trends_user ON osintgram.rss_trends(user_id);
        CREATE INDEX IF NOT EXISTS idx_rss_trends_fetched ON osintgram.rss_trends(fetched_at);
        CREATE INDEX IF NOT EXISTS idx_content_ideas_user ON osintgram.content_ideas(user_id);
        CREATE INDEX IF NOT EXISTS idx_content_ideas_status ON osintgram.content_ideas(status);
        CREATE INDEX IF NOT EXISTS idx_generated_media_user ON osintgram.generated_media(user_id);
    """)
    print("  ✅ Індекси створені")
    
    cursor.close()
    conn.close()
    
    print("\n✅ Міграція завершена!")
    
except Exception as e:
    print(f"❌ Помилка: {e}")
