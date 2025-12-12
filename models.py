"""
SQLAlchemy models for Instagram OSINT application.
Includes User, InstagramAccount, Follower, ParseSession, PublishedContent, ExportHistory.
All tables are created in 'osintgram' schema for isolation.
"""
from database import db, SCHEMA_NAME
from flask_login import UserMixin
from datetime import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash


# ============ USER TABLE ============

class User(UserMixin, db.Model):
    """Таблица пользователей приложения"""
    __tablename__ = 'users'
    __table_args__ = {'schema': SCHEMA_NAME}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    company_name = db.Column(db.String(255))
    
    # Профиль
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    profile_picture_url = db.Column(db.String(500))
    
    # Даты
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Отношения
    instagram_accounts = db.relationship('InstagramAccount', back_populates='user', cascade='all, delete-orphan')
    parse_sessions = db.relationship('ParseSession', back_populates='user', cascade='all, delete-orphan')
    followers = db.relationship('Follower', back_populates='user', cascade='all, delete-orphan')
    
    def set_password(self, password: str) -> None:
        """
        Хеширование пароля
        
        Args:
            password: Пароль в открытом виде
        """
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password: str) -> bool:
        """
        Проверка пароля
        
        Args:
            password: Пароль для проверки
            
        Returns:
            bool: True если пароль верный
        """
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.email}>'


# ============ INSTAGRAM ACCOUNTS TABLE ============

class InstagramAccount(db.Model):
    """Таблица Instagram аккаунтов пользователя"""
    __tablename__ = 'instagram_accounts'
    __table_args__ = (
        db.Index('idx_user_instagram_username', 'user_id', 'instagram_username'),
        {'schema': SCHEMA_NAME}
    )
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.users.id'), nullable=False, index=True)
    
    # Данные аккаунта
    instagram_username = db.Column(db.String(255), nullable=False)
    instagram_user_id = db.Column(db.String(255), unique=True)
    instagram_password = db.Column(db.String(500), nullable=False)  # В production зашифровать!
    
    # Информация профиля
    full_name = db.Column(db.String(255))
    biography = db.Column(db.Text)
    profile_pic_url = db.Column(db.Text)  # Text для длинных URL
    followers_count = db.Column(db.Integer)
    following_count = db.Column(db.Integer)
    posts_count = db.Column(db.Integer)
    is_verified = db.Column(db.Boolean, default=False)
    is_business = db.Column(db.Boolean, default=False)
    is_private = db.Column(db.Boolean, default=False)
    
    # Статус
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    
    # Даты
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Отношения
    user = db.relationship('User', back_populates='instagram_accounts')
    parse_sessions = db.relationship('ParseSession', back_populates='instagram_account', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<InstagramAccount {self.instagram_username}>'


# ============ FOLLOWERS TABLE ============

class Follower(db.Model):
    """Таблица подписчиков собранных с конкурентских аккаунтов"""
    __tablename__ = 'followers'
    __table_args__ = (
        db.Index('idx_user_username_unique', 'user_id', 'instagram_user_id', unique=True),
        db.Index('idx_user_source_account', 'user_id', 'source_account_username'),
        {'schema': SCHEMA_NAME}
    )
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.users.id'), nullable=False, index=True)
    parse_session_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.parse_sessions.id'), index=True)
    
    # Данные подписчика
    instagram_user_id = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255), nullable=False, index=True)
    full_name = db.Column(db.String(255))
    biography = db.Column(db.Text)
    profile_pic_url = db.Column(db.Text)  # Text для длинных URL
    
    # Статистика подписчика
    followers_count = db.Column(db.Integer)
    following_count = db.Column(db.Integer)
    posts_count = db.Column(db.Integer)
    
    # Метаданные
    is_verified = db.Column(db.Boolean, default=False)
    is_business = db.Column(db.Boolean, default=False)
    is_private = db.Column(db.Boolean, default=False)
    
    # Контакты (парсинг из bio)
    email = db.Column(db.String(255), index=True)
    phone = db.Column(db.String(50))
    website_url = db.Column(db.Text)  # Text для длинных URL
    
    # Теги из биографии (для анализа)
    tags_from_bio = db.Column(db.JSON)  # ['#travel', '#photographer']
    
    # Исходные данные
    source_account_username = db.Column(db.String(255), nullable=False)  # чей подписчик
    
    # Качество контакта
    quality_score = db.Column(db.Integer, default=0)  # 0-100
    
    # Даты
    collected_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Отношения
    user = db.relationship('User', back_populates='followers')
    parse_session = db.relationship('ParseSession', back_populates='followers')
    
    def __repr__(self):
        return f'<Follower {self.username}>'


# ============ PARSE SESSIONS TABLE ============

class ParseSession(db.Model):
    """Таблица сессий парсинга"""
    __tablename__ = 'parse_sessions'
    __table_args__ = (
        db.Index('idx_user_created', 'user_id', 'started_at'),
        {'schema': SCHEMA_NAME}
    )
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.users.id'), nullable=False, index=True)
    instagram_account_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.instagram_accounts.id'), index=True)
    
    # Данные сессии
    competitor_usernames = db.Column(db.JSON, nullable=False)  # ['username1', 'username2']
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    
    # Результаты
    total_followers_collected = db.Column(db.Integer, default=0)
    unique_followers_count = db.Column(db.Integer, default=0)
    failed_accounts = db.Column(db.JSON)  # {'username': 'error_message'}
    
    # Детали
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    
    # Отношения
    user = db.relationship('User', back_populates='parse_sessions')
    instagram_account = db.relationship('InstagramAccount', back_populates='parse_sessions')
    followers = db.relationship('Follower', back_populates='parse_session', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ParseSession {self.id}>'


# ============ PUBLISHED CONTENT TABLE ============

class PublishedContent(db.Model):
    """Таблица опубликованного контента"""
    __tablename__ = 'published_content'
    __table_args__ = {'schema': SCHEMA_NAME}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.users.id'), nullable=False, index=True)
    instagram_account_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.instagram_accounts.id'), nullable=False)
    
    # Контент
    content_type = db.Column(db.String(50), nullable=False)  # 'post', 'story', 'carousel', 'reel'
    caption = db.Column(db.Text)
    media_urls = db.Column(db.JSON)  # список URL/путей медиафайлов
    
    # Результат публикации
    instagram_media_id = db.Column(db.String(255), unique=True)
    status = db.Column(db.String(50), default='pending')  # pending, published, failed
    instagram_url = db.Column(db.String(500))  # ссылка на пост в Instagram
    error_message = db.Column(db.Text)
    
    # Статистика
    likes_count = db.Column(db.Integer, default=0)
    comments_count = db.Column(db.Integer, default=0)
    views_count = db.Column(db.Integer, default=0)
    
    # Даты
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    published_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PublishedContent {self.id}>'


# ============ EXPORT HISTORY TABLE ============

class ExportHistory(db.Model):
    """История экспортов для Meta Ads"""
    __tablename__ = 'export_history'
    __table_args__ = {'schema': SCHEMA_NAME}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey(f'{SCHEMA_NAME}.users.id'), nullable=False)
    
    # Параметры экспорта
    export_type = db.Column(db.String(50), nullable=False)  # 'csv', 'json', 'meta_ads'
    filters_applied = db.Column(db.JSON)  # примененные фильтры
    
    # Результат
    rows_exported = db.Column(db.Integer)
    file_url = db.Column(db.String(500))  # где скачать файл
    file_size_kb = db.Column(db.Integer)
    
    # Даты
    exported_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ExportHistory {self.id}>'
