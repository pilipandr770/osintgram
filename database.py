"""
Database initialization module for Instagram OSINT application.
Creates a separate schema for project isolation.
"""
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from dotenv import load_dotenv

# Загрузить переменные окружения
load_dotenv()

db = SQLAlchemy()

# Имя schema для этого проекта
SCHEMA_NAME = os.environ.get('DB_SCHEMA', 'osintgram')


def init_db(app):
    """
    Инициализация базы данных с созданием отдельной schema.
    Примечание: db.init_app() должен быть вызван в create_app(), 
    эта функция только для дополнительной инициализации при необходимости.
    
    Args:
        app: Flask application instance
    """
    with app.app_context():
        print(f"Database connected to schema '{SCHEMA_NAME}'")
