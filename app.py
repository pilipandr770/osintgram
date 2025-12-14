"""
Main Flask application for Instagram OSINT.
Contains all routes for dashboard, accounts, parsing, followers, export, and publishing.
"""
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from config import config
from database import db, init_db
from models import User, InstagramAccount, Follower, ParseSession, PublishedContent, ExportHistory, MessageLog, SentMessage, RssTrend, ContentIdea, AutomationSettings, AiCache, DmAssistantSettings, InviteCampaignSettings
from instagram_service import InstagramService
from encryption import encrypt_password, decrypt_password
from geo_search import analyze_profile_relevance, HASHTAGS_SEARCH
from ai_service import analyze_profile, generate_personalized_message, generate_post_content, batch_analyze_profiles, summarize_trend, OPENAI_API_KEY
from rss_service import get_trending_topics, generate_content_ideas_from_trends
from auth import auth_bp
import os
from datetime import datetime
from io import BytesIO, StringIO
import csv
from dotenv import load_dotenv
import uuid
from media_utils import normalize_to_jpeg

# Загрузить переменные окружения
load_dotenv()


def create_app(config_name=None):
    """
    Application factory для Flask приложения
    
    Args:
        config_name: имя конфигурации (development, production, testing)
        
    Returns:
        Flask: сконфигурированное приложение
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Инициализация расширений
    db.init_app(app)
    migrate = Migrate(app, db)
    
    # Login Manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите в систему'
    login_manager.login_message_category = 'warning'
    
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, user_id)
    
    # Регистрация blueprints
    app.register_blueprint(auth_bp)
    
    # Создать schema и таблицы при первом запуске
    with app.app_context():
        # Сначала создаём schema
        from database import SCHEMA_NAME
        from sqlalchemy import text
        with db.engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}'))
            conn.commit()
            print(f"Schema '{SCHEMA_NAME}' создана или уже существует")
        
        # Затем создаём таблицы
        db.create_all()
        print(f"Все таблицы созданы в schema '{SCHEMA_NAME}'")
    
    # ============ ROUTES ============
    
    @app.route('/')
    def index():
        """Главная страница - редирект на дашборд или логин"""
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('auth.login'))
    
    @app.route('/dashboard')
    @login_required
    def dashboard():
        """Дашборд пользователя со статистикой"""
        user_id = current_user.id
        
        # Статистика
        instagram_accounts_count = InstagramAccount.query.filter_by(user_id=user_id).count()
        total_followers = Follower.query.filter_by(user_id=user_id).count()
        parse_sessions_count = ParseSession.query.filter_by(user_id=user_id).count()
        
        # Подписчики с email
        followers_with_email = Follower.query.filter(
            Follower.user_id == user_id,
            Follower.email.isnot(None)
        ).count()
        
        # Последние сессии парсинга
        recent_sessions = ParseSession.query.filter_by(user_id=user_id).order_by(
            ParseSession.started_at.desc()
        ).limit(5).all()
        
        return render_template('dashboard.html',
            instagram_accounts_count=instagram_accounts_count,
            total_followers=total_followers,
            followers_with_email=followers_with_email,
            parse_sessions_count=parse_sessions_count,
            recent_sessions=recent_sessions
        )
    
    @app.route('/accounts', methods=['GET', 'POST'])
    @login_required
    def manage_accounts():
        """Управление Instagram аккаунтами"""
        if request.method == 'POST':
            username = request.form.get('instagram_username', '').strip().lstrip('@')
            password = request.form.get('instagram_password', '')
            proxy_str = request.form.get('proxy', '').strip()
            
            if not username or not password:
                flash('Введите username и пароль', 'error')
                return redirect(url_for('manage_accounts'))
            
            # Проверить не существует ли уже такой аккаунт
            existing = InstagramAccount.query.filter_by(
                user_id=current_user.id,
                instagram_username=username
            ).first()
            
            if existing:
                flash('Этот аккаунт уже добавлен', 'error')
                return redirect(url_for('manage_accounts'))
            
            # Настройка прокси
            proxy = None
            if proxy_str:
                proxy = {'http': proxy_str, 'https': proxy_str}
                flash(f'Используем прокси: {proxy_str}', 'info')
            
            # Попробовать войти в аккаунт
            flash('Проверяем данные аккаунта...', 'info')
            service = InstagramService(username, password, proxy=proxy)
            success, message = service.login()
            
            if not success:
                flash(f'Ошибка входа: {message}', 'error')
                return redirect(url_for('manage_accounts'))
            
            # Получить информацию о профиле
            account_info = service.get_account_info()
            if not account_info:
                flash('Не удалось получить информацию о профиле', 'error')
                return redirect(url_for('manage_accounts'))
            
            # Сохранить аккаунт
            try:
                # 🔐 Шифруємо пароль перед збереженням
                encrypted_pwd = encrypt_password(password)
                
                instagram_account = InstagramAccount(
                    user_id=current_user.id,
                    instagram_username=username,
                    instagram_password=encrypted_pwd,  # 🔐 Зашифровано!
                    instagram_user_id=account_info.get('user_id'),
                    full_name=account_info.get('full_name'),
                    biography=account_info.get('biography'),
                    profile_pic_url=account_info.get('profile_pic_url'),
                    followers_count=account_info.get('followers_count'),
                    following_count=account_info.get('following_count'),
                    posts_count=account_info.get('posts_count'),
                    is_verified=account_info.get('is_verified', False),
                    is_business=account_info.get('is_business', False),
                    is_private=account_info.get('is_private', False),
                    last_sync=datetime.utcnow()
                )
                db.session.add(instagram_account)
                db.session.commit()
                
                flash(f'Аккаунт @{username} успешно добавлен!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка сохранения: {str(e)}', 'error')
            
            return redirect(url_for('manage_accounts'))
        
        # GET - вывести список аккаунтов
        accounts = InstagramAccount.query.filter_by(user_id=current_user.id).all()
        return render_template('add_account.html', accounts=accounts)
    
    @app.route('/accounts/<account_id>/delete', methods=['POST'])
    @login_required
    def delete_account(account_id):
        """Удаление Instagram аккаунта"""
        account = InstagramAccount.query.filter_by(
            id=account_id,
            user_id=current_user.id
        ).first()
        
        if not account:
            flash('Аккаунт не найден', 'error')
            return redirect(url_for('manage_accounts'))
        
        try:
            # Best-effort: remove local instagrapi session file for this username
            try:
                session_path = os.path.join(os.path.dirname(__file__), 'sessions', f"{account.instagram_username}_session.json")
                if os.path.exists(session_path):
                    os.remove(session_path)
            except Exception:
                pass

            # Remove dependent rows to avoid FK constraint errors
            from models import (
                DmAssistantSettings, DmThreadState, DmMessage,
                InviteCampaignSettings, InviteCampaignRecipient, InviteCampaignSend,
                PublishedContent, MessageLog,
            )

            # DM assistant
            DmMessage.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)
            DmThreadState.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)
            DmAssistantSettings.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)

            # Invite campaign
            InviteCampaignSend.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)
            InviteCampaignRecipient.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)
            InviteCampaignSettings.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)

            # Published content history
            PublishedContent.query.filter_by(instagram_account_id=account.id).delete(synchronize_session=False)

            # Manual Direct blast logs: delete SentMessage rows linked to MessageLog, then MessageLog
            log_ids = [r[0] for r in db.session.query(MessageLog.id).filter_by(account_id=account.id).all()]
            if log_ids:
                SentMessage.query.filter(SentMessage.message_log_id.in_(log_ids)).delete(synchronize_session=False)
                MessageLog.query.filter(MessageLog.id.in_(log_ids)).delete(synchronize_session=False)

            db.session.delete(account)
            db.session.commit()
            flash(f'Аккаунт @{account.instagram_username} удален', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка удаления: {str(e)}', 'error')
        
        return redirect(url_for('manage_accounts'))

    @app.route('/accounts/<account_id>/password', methods=['POST'])
    @login_required
    def update_account_password(account_id):
        """Re-save Instagram password (encrypt again) and verify login."""
        account = InstagramAccount.query.filter_by(
            id=account_id,
            user_id=current_user.id
        ).first()

        if not account:
            flash('Аккаунт не найден', 'error')
            return redirect(url_for('manage_accounts'))

        new_password = request.form.get('new_instagram_password', '')
        if not new_password:
            flash('Введите новый пароль', 'error')
            return redirect(url_for('manage_accounts'))

        # Verify credentials before saving
        flash('Проверяем новый пароль...', 'info')
        service = InstagramService(account.instagram_username, new_password)
        success, message = service.login()
        if not success:
            flash(f'Ошибка входа: {message}', 'error')
            return redirect(url_for('manage_accounts'))

        try:
            account.instagram_password = encrypt_password(new_password)

            # Remove local instagrapi session file to avoid stale sessions
            try:
                session_path = os.path.join(os.path.dirname(__file__), 'sessions', f"{account.instagram_username}_session.json")
                if os.path.exists(session_path):
                    os.remove(session_path)
            except Exception:
                pass

            db.session.commit()
            flash(f'Пароль для @{account.instagram_username} обновлен', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка сохранения пароля: {str(e)}', 'error')

        return redirect(url_for('manage_accounts'))
    
    @app.route('/parse', methods=['GET', 'POST'])
    @login_required
    def parse_competitors():
        """Аналіз публічно доступних профілів"""
        if request.method == 'POST':
            competitor_usernames_str = request.form.get('competitor_usernames', '')
            instagram_account_id = request.form.get('instagram_account_id')
            max_followers = int(request.form.get('max_followers', 10000))
            
            # Парсимо username'и (розділяються комами)
            competitor_usernames = [
                username.strip().lstrip('@') for username in competitor_usernames_str.split(',')
                if username.strip()
            ]
            
            if not competitor_usernames:
                flash('Введіть хоча б один username спільноти', 'error')
                return redirect(url_for('parse_competitors'))
            
            if not instagram_account_id:
                flash('Выберите Instagram аккаунт для парсинга', 'error')
                return redirect(url_for('parse_competitors'))
            
            # Проверить существует ли аккаунт
            account = InstagramAccount.query.filter_by(
                id=instagram_account_id,
                user_id=current_user.id
            ).first()
            
            if not account:
                flash('Instagram аккаунт не найден', 'error')
                return redirect(url_for('parse_competitors'))
            
            # Создать сессию парсинга
            parse_session = ParseSession(
                user_id=current_user.id,
                instagram_account_id=instagram_account_id,
                competitor_usernames=competitor_usernames,
                status='processing'
            )
            db.session.add(parse_session)
            db.session.commit()
            
            # Начать парсинг
            try:
                # 🔐 Розшифровуємо пароль
                decrypted_pwd = decrypt_password(account.instagram_password)
                service = InstagramService(account.instagram_username, decrypted_pwd)
                success, message = service.login()
                
                if not success:
                    parse_session.status = 'failed'
                    parse_session.error_message = f'Ошибка входа: {message}'
                    db.session.commit()
                    flash(f'Ошибка входа в аккаунт: {message}', 'error')
                    return redirect(url_for('parse_competitors'))
                
                # Парсить подписчиков
                total_collected, failed_accounts = service.parse_competitors(
                    competitor_usernames,
                    parse_session.id,
                    current_user.id,
                    max_followers
                )
                
                if failed_accounts:
                    failed_msg = ', '.join([f"@{k}: {v}" for k, v in failed_accounts.items()])
                    flash(f'Деякі акаунти не вдалося обробити: {failed_msg}', 'warning')
                
                flash(f'✅ Зібрано {total_collected} профілів!', 'success')
                return redirect(url_for('followers_table', session_id=parse_session.id))
            
            except Exception as e:
                parse_session.status = 'failed'
                parse_session.error_message = str(e)
                parse_session.completed_at = datetime.utcnow()
                db.session.commit()
                flash(f'Ошибка при парсинге: {str(e)}', 'error')
                return redirect(url_for('parse_competitors'))
        
        # GET - форма для парсинга
        accounts = InstagramAccount.query.filter_by(user_id=current_user.id).all()
        return render_template('parse_competitors.html', accounts=accounts)
    
    @app.route('/discover', methods=['GET', 'POST'])
    @login_required
    def discover_accounts():
        """🔍 Автоматичний пошук схожих сторінок (ремонт/кафель біля Франкфурта)"""
        if request.method == 'POST':
            instagram_account_id = request.form.get('instagram_account_id')
            
            if not instagram_account_id:
                flash('Оберіть Instagram акаунт для пошуку', 'error')
                return redirect(url_for('discover_accounts'))
            
            account = InstagramAccount.query.filter_by(
                id=instagram_account_id,
                user_id=current_user.id
            ).first()
            
            if not account:
                flash('Instagram акаунт не знайдено', 'error')
                return redirect(url_for('discover_accounts'))
            
            try:
                # 🔐 Розшифровуємо пароль
                decrypted_pwd = decrypt_password(account.instagram_password)
                service = InstagramService(account.instagram_username, decrypted_pwd)
                success, message = service.login()
                
                if not success:
                    flash(f'Помилка входу: {message}', 'error')
                    return redirect(url_for('discover_accounts'))
                
                # 🔍 Пошук схожих акаунтів
                flash('🔍 Шукаємо схожі акаунти... Це може зайняти 1-2 хвилини', 'info')
                discovered = service.discover_similar_accounts()
                
                # Зберігаємо в сесії для відображення
                from flask import session as flask_session
                flask_session['discovered_accounts'] = discovered[:30]  # Топ-30
                
                flash(f'✅ Знайдено {len(discovered)} потенційних акаунтів!', 'success')
                return redirect(url_for('discover_accounts'))
                
            except Exception as e:
                flash(f'Помилка пошуку: {str(e)}', 'error')
                return redirect(url_for('discover_accounts'))
        
        # GET - показати форму та результати
        from flask import session as flask_session
        discovered = flask_session.get('discovered_accounts', [])
        accounts = InstagramAccount.query.filter_by(user_id=current_user.id).all()
        
        return render_template('discover.html', 
                               accounts=accounts, 
                               discovered=discovered,
                               hashtags=HASHTAGS_SEARCH[:10])
    
    @app.route('/import', methods=['POST'])
    @login_required
    def import_followers():
        """Імпорт публічних профілів з файлу або тексту"""
        source_account = request.form.get('source_account', '').strip().lstrip('@')
        manual_usernames = request.form.get('manual_usernames', '').strip()
        
        print(f"DEBUG: source_account = '{source_account}'")
        print(f"DEBUG: manual_usernames = '{manual_usernames}'")
        print(f"DEBUG: files = {request.files}")
        
        if not source_account:
            flash('Вкажіть джерело даних (назва спільноти)', 'error')
            return redirect(url_for('parse_competitors'))
        
        usernames = []
        
        # Проверяем загруженный файл
        if 'import_file' in request.files:
            file = request.files['import_file']
            print(f"DEBUG: file = {file}, filename = {file.filename if file else 'None'}")
            if file and file.filename:
                try:
                    content = file.read().decode('utf-8', errors='ignore')
                    print(f"DEBUG: file content length = {len(content)}")
                    print(f"DEBUG: file content preview = {content[:200]}")
                    # Парсим содержимое файла
                    for line in content.replace(',', '\n').split('\n'):
                        username = line.strip().lstrip('@').strip()
                        if username and len(username) > 0:
                            usernames.append(username)
                except Exception as e:
                    flash(f'Ошибка чтения файла: {str(e)}', 'error')
                    return redirect(url_for('parse_competitors'))
        
        # Добавляем username'ы из текстового поля
        if manual_usernames:
            for line in manual_usernames.replace(',', '\n').split('\n'):
                username = line.strip().lstrip('@').strip()
                if username and len(username) > 0 and username not in usernames:
                    usernames.append(username)
        
        print(f"DEBUG: parsed usernames count = {len(usernames)}")
        print(f"DEBUG: first 10 usernames = {usernames[:10]}")
        
        if not usernames:
            flash('Не найдено ни одного username. Загрузите файл или введите вручную.', 'error')
            return redirect(url_for('parse_competitors'))
        
        # Создаём сессию импорта
        parse_session = ParseSession(
            user_id=current_user.id,
            competitor_usernames=source_account,
            status='completed',
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        db.session.add(parse_session)
        db.session.flush()
        
        # Добавляем подписчиков в базу
        imported_count = 0
        skipped_count = 0
        
        for username in usernames:
            # Проверяем, нет ли уже такого подписчика
            existing = Follower.query.filter_by(
                user_id=current_user.id,
                username=username
            ).first()
            
            if existing:
                skipped_count += 1
                continue
            
            # Создаём запись подписчика
            # ✅ Все подписчики конкурентов = целевая аудитория!
            follower = Follower(
                user_id=current_user.id,
                parse_session_id=parse_session.id,
                instagram_user_id=username,  # Используем username как временный ID
                username=username,
                source_account_username=source_account,
                collected_at=datetime.utcnow(),
                is_target_audience=True,  # Всі підписчики конкурентів - цільові
                is_frankfurt_region=True,  # Припускаємо регіон Франкфурт
                interest_score=50  # Базовий рейтинг інтересу
            )
            db.session.add(follower)
            imported_count += 1
        
        # Обновляем статистику сессии
        parse_session.total_collected = imported_count
        
        try:
            db.session.commit()
            flash(f'✅ Імпортовано {imported_count} профілів з @{source_account}. Пропущено дублікатів: {skipped_count}', 'success')
            return redirect(url_for('followers_table', session_id=parse_session.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Помилка збереження: {str(e)}', 'error')
            return redirect(url_for('parse_competitors'))
    
    @app.route('/followers')
    @login_required
    def followers_table():
        """Таблиця аудиторії з фільтрацією та пагінацією"""
        session_id = request.args.get('session_id')
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('ITEMS_PER_PAGE', 50)
        
        # Фильтры
        min_followers = request.args.get('min_followers', 0, type=int)
        has_email = request.args.get('has_email') == 'on'
        is_verified = request.args.get('is_verified') == 'on'
        is_business = request.args.get('is_business') == 'on'
        source_account = request.args.get('source_account', '').strip()
        
        # Query
        query = Follower.query.filter_by(user_id=current_user.id)
        
        if session_id:
            query = query.filter_by(parse_session_id=session_id)
        
        if min_followers > 0:
            query = query.filter(Follower.followers_count >= min_followers)
        
        if has_email:
            query = query.filter(Follower.email.isnot(None))
        
        if is_verified:
            query = query.filter_by(is_verified=True)
        
        if is_business:
            query = query.filter_by(is_business=True)
        
        if source_account:
            query = query.filter(Follower.source_account_username.ilike(f'%{source_account}%'))
        
        # Сортировка по quality_score
        query = query.order_by(Follower.quality_score.desc())
        
        # Пагинация
        followers = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Получить список источников для фильтра
        source_accounts = db.session.query(Follower.source_account_username).filter_by(
            user_id=current_user.id
        ).distinct().all()
        source_accounts = [s[0] for s in source_accounts]
        
        return render_template('followers_table.html',
            followers=followers,
            source_accounts=source_accounts,
            session_id=session_id
        )
    
    @app.route('/export/csv')
    @login_required
    def export_csv():
        """Экспорт подписчиков в CSV для Meta Ads"""
        session_id = request.args.get('session_id')
        
        # Фильтры (те же что в таблице)
        min_followers = request.args.get('min_followers', 0, type=int)
        has_email = request.args.get('has_email') == 'on'
        is_verified = request.args.get('is_verified') == 'on'
        
        # Query
        query = Follower.query.filter_by(user_id=current_user.id)
        
        if session_id:
            query = query.filter_by(parse_session_id=session_id)
        
        if min_followers > 0:
            query = query.filter(Follower.followers_count >= min_followers)
        
        if has_email:
            query = query.filter(Follower.email.isnot(None))
        
        if is_verified:
            query = query.filter_by(is_verified=True)
        
        followers = query.order_by(Follower.quality_score.desc()).all()
        
        # Создать CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Header для Meta Ads Custom Audience
        writer.writerow([
            'email',
            'phone',
            'fn',  # first name
            'ln',  # last name  
            'country',
            'external_id'
        ])
        
        # Данные
        for follower in followers:
            # Разделяем full_name на first/last name
            name_parts = (follower.full_name or '').split(' ', 1)
            first_name = name_parts[0] if name_parts else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            writer.writerow([
                follower.email or '',
                follower.phone or '',
                first_name,
                last_name,
                '',  # country - можно добавить определение по username
                follower.instagram_user_id
            ])
        
        # Сохранить историю экспорта
        try:
            export_history = ExportHistory(
                user_id=current_user.id,
                export_type='csv',
                rows_exported=len(followers),
                filters_applied={
                    'session_id': session_id,
                    'min_followers': min_followers,
                    'has_email': has_email,
                    'is_verified': is_verified
                }
            )
            db.session.add(export_history)
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        # Возврат файла
        output.seek(0)
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'followers_meta_ads_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    
    @app.route('/export/full-csv')
    @login_required
    def export_full_csv():
        """Экспорт всех данных подписчиков в CSV"""
        session_id = request.args.get('session_id')
        
        query = Follower.query.filter_by(user_id=current_user.id)
        if session_id:
            query = query.filter_by(parse_session_id=session_id)
        
        followers = query.order_by(Follower.quality_score.desc()).all()
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Полный header
        writer.writerow([
            'Username',
            'Full Name',
            'Followers',
            'Following',
            'Posts',
            'Email',
            'Phone',
            'Website',
            'Is Verified',
            'Is Business',
            'Is Private',
            'Biography',
            'Source Account',
            'Quality Score',
            'Collected At'
        ])
        
        for follower in followers:
            writer.writerow([
                follower.username,
                follower.full_name or '',
                follower.followers_count or 0,
                follower.following_count or 0,
                follower.posts_count or 0,
                follower.email or '',
                follower.phone or '',
                follower.website_url or '',
                'Yes' if follower.is_verified else 'No',
                'Yes' if follower.is_business else 'No',
                'Yes' if follower.is_private else 'No',
                (follower.biography or '')[:200],  # Обрезаем био
                follower.source_account_username,
                follower.quality_score,
                follower.collected_at.strftime('%Y-%m-%d %H:%M') if follower.collected_at else ''
            ])
        
        output.seek(0)
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'followers_full_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    
    @app.route('/publish', methods=['GET', 'POST'])
    @login_required
    def publish_content():
        """Публикация контента в Instagram"""
        if request.method == 'POST':
            instagram_account_id = request.form.get('instagram_account_id')
            content_type = request.form.get('content_type')  # 'post', 'story', 'carousel'
            caption = request.form.get('caption', '')
            
            # Получить файлы
            files = request.files.getlist('media_files')
            
            if not files or not files[0].filename:
                flash('Выберите хотя бы один файл', 'error')
                return redirect(url_for('publish_content'))
            
            # Проверить аккаунт
            account = InstagramAccount.query.filter_by(
                id=instagram_account_id,
                user_id=current_user.id
            ).first()
            
            if not account:
                flash('Instagram аккаунт не найден', 'error')
                return redirect(url_for('publish_content'))
            
            try:
                # 🔐 Розшифровуємо пароль
                decrypted_pwd = decrypt_password(account.instagram_password)
                service = InstagramService(account.instagram_username, decrypted_pwd)
                success, login_msg = service.login()
                
                if not success:
                    flash(f'Ошибка входа: {login_msg}', 'error')
                    return redirect(url_for('publish_content'))
                
                # Создать папку для uploads если нет
                upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)

                normalized_folder = os.path.join(upload_folder, 'normalized')
                os.makedirs(normalized_folder, exist_ok=True)
                
                # Save uploaded files and normalize images to JPEG (instagrapi photo upload requires JPG/JPEG)
                temp_paths = []
                media_paths = []
                for file in files:
                    if not file.filename:
                        continue

                    tmp_name = f"upload_{uuid.uuid4().hex}"
                    tmp_path = os.path.join(upload_folder, tmp_name)
                    file.save(tmp_path)
                    temp_paths.append(tmp_path)

                    # Convert to JPG
                    jpg_path = os.path.join(normalized_folder, f"{uuid.uuid4().hex}.jpg")
                    try:
                        normalize_to_jpeg(tmp_path, jpg_path)
                        media_paths.append(jpg_path)
                    except Exception as e:
                        # cleanup and show readable error
                        for p in temp_paths:
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        for p in media_paths:
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        flash(f'Ошибка файла: {str(e)}. Для публикации используйте изображения.', 'error')
                        return redirect(url_for('publish_content'))
                
                # Опубликовать
                if content_type == 'post' and len(media_paths) == 1:
                    is_success, result = service.publish_post(caption, media_paths[0])
                elif content_type == 'story' and len(media_paths) >= 1:
                    is_success, result = service.publish_story(media_paths[0])
                elif content_type == 'carousel' and len(media_paths) > 1:
                    is_success, result = service.publish_carousel(caption, media_paths)
                else:
                    is_success, result = False, 'Неизвестный тип контента или неверное количество файлов'
                
                # Сохранить в БД
                published_content = PublishedContent(
                    user_id=current_user.id,
                    instagram_account_id=instagram_account_id,
                    content_type=content_type,
                    caption=caption,
                    media_urls=[f.filename for f in files if f.filename],
                    status='published' if is_success else 'failed',
                    instagram_media_id=result if is_success else None,
                    error_message=result if not is_success else None,
                    published_at=datetime.utcnow() if is_success else None
                )
                db.session.add(published_content)
                db.session.commit()
                
                # Удалить временные файлы
                for path in temp_paths:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                for path in media_paths:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                
                if is_success:
                    flash('Контент успешно опубликован!', 'success')
                else:
                    flash(f'Ошибка публикации: {result}', 'error')
                
                return redirect(url_for('publish_content'))
            
            except Exception as e:
                flash(f'Ошибка: {str(e)}', 'error')
                return redirect(url_for('publish_content'))
        
        # GET - форма для публикации
        accounts = InstagramAccount.query.filter_by(user_id=current_user.id).all()
        
        # История публикаций
        publications = PublishedContent.query.filter_by(
            user_id=current_user.id
        ).order_by(PublishedContent.created_at.desc()).limit(10).all()
        
        return render_template('publish.html', accounts=accounts, publications=publications)
    
    @app.route('/statistics')
    @login_required
    def statistics():
        """Страница статистики парсинга"""
        user_id = current_user.id
        
        # Все сессии парсинга
        sessions = ParseSession.query.filter_by(user_id=user_id).order_by(
            ParseSession.started_at.desc()
        ).all()
        
        # Общая статистика
        total_followers = Follower.query.filter_by(user_id=user_id).count()
        followers_with_email = Follower.query.filter(
            Follower.user_id == user_id,
            Follower.email.isnot(None)
        ).count()
        verified_followers = Follower.query.filter_by(user_id=user_id, is_verified=True).count()
        business_followers = Follower.query.filter_by(user_id=user_id, is_business=True).count()
        
        # История экспортов
        exports = ExportHistory.query.filter_by(user_id=user_id).order_by(
            ExportHistory.exported_at.desc()
        ).limit(10).all()
        
        return render_template('statistics.html',
            sessions=sessions,
            total_followers=total_followers,
            followers_with_email=followers_with_email,
            verified_followers=verified_followers,
            business_followers=business_followers,
            exports=exports
        )
    
    # ============ MESSAGING ROUTES ============
    
    @app.route('/messaging')
    @login_required
    def messaging():
        """📨 Сторінка розсилки повідомлень в Direct"""
        user_id = current_user.id
        
        # Статистика
        total_followers = Follower.query.filter_by(user_id=user_id).count()
        target_audience = Follower.query.filter_by(user_id=user_id, is_target_audience=True).count()
        frankfurt_region = Follower.query.filter_by(user_id=user_id, is_frankfurt_region=True).count()
        
        # Скільки повідомлень відправлено сьогодні
        from datetime import date
        today = date.today()
        messages_sent_today = SentMessage.query.filter(
            SentMessage.user_id == user_id,
            db.func.date(SentMessage.sent_at) == today
        ).count()
        
        # Денний ліміт (безпечний)
        daily_limit = 20
        
        # Акаунти
        accounts = InstagramAccount.query.filter_by(user_id=user_id).all()

        dm_rows = DmAssistantSettings.query.filter_by(user_id=user_id).all()

        # DM assistant settings (per IG account)
        dm_settings_by_account = {s.instagram_account_id: s for s in dm_rows}
        dm_settings_json = {
            str(s.instagram_account_id): {
                'enabled': bool(s.enabled),
                'reply_to_existing_threads': bool(getattr(s, 'reply_to_existing_threads', False)),
                'language': (s.language or 'ru'),
                'max_replies_per_day': int(s.max_replies_per_day or 20),
                'system_instructions': (s.system_instructions or ''),
            }
            for s in dm_rows
        }

        invite_rows = InviteCampaignSettings.query.filter_by(user_id=user_id).all()
        invite_settings_json = {
            str(s.instagram_account_id): {
                'enabled': bool(s.enabled),
                'audience_type': (s.audience_type or 'target'),
                'max_sends_per_day': int(s.max_sends_per_day or 20),
                'min_delay_seconds': int(s.min_delay_seconds or 45),
                'max_delay_seconds': int(s.max_delay_seconds or 75),
                'stop_on_inbound_reply': bool(s.stop_on_inbound_reply),
                'steps': (s.steps or []),
            }
            for s in invite_rows
        }
        
        # Історія розсилок
        message_logs = MessageLog.query.filter_by(user_id=user_id).order_by(
            MessageLog.created_at.desc()
        ).limit(20).all()
        
        return render_template('messaging.html',
            total_followers=total_followers,
            target_audience=target_audience,
            frankfurt_region=frankfurt_region,
            messages_sent_today=messages_sent_today,
            daily_limit=daily_limit,
            accounts=accounts,
            message_logs=message_logs,
            dm_settings_by_account=dm_settings_by_account,
            dm_settings_json=dm_settings_json,
            invite_settings_json=invite_settings_json,
        )

    @app.route('/dm-assistant/settings', methods=['POST'])
    @login_required
    def dm_assistant_save_settings():
        """Save OpenAI-powered DM auto-reply instructions/settings."""
        user_id = current_user.id
        account_id = (request.form.get('account_id') or '').strip()
        if not account_id:
            flash('Оберіть акаунт для авто-відповідача', 'error')
            return redirect(url_for('messaging'))

        account = InstagramAccount.query.filter_by(id=account_id, user_id=user_id).first()
        if not account:
            flash('Акаунт не знайдено', 'error')
            return redirect(url_for('messaging'))

        enabled = bool(request.form.get('enabled'))
        reply_to_existing = bool(request.form.get('reply_to_existing_threads'))
        instructions = (request.form.get('system_instructions') or '').strip()
        language = (request.form.get('language') or 'ru').strip()[:16]

        try:
            max_replies_per_day = int(request.form.get('max_replies_per_day', 20))
        except Exception:
            max_replies_per_day = 20

        settings = DmAssistantSettings.query.filter_by(user_id=user_id, instagram_account_id=account_id).first()
        if settings is None:
            settings = DmAssistantSettings(user_id=user_id, instagram_account_id=account_id)
            db.session.add(settings)

        settings.enabled = enabled
        settings.reply_to_existing_threads = reply_to_existing
        settings.system_instructions = instructions
        settings.language = language or 'ru'
        settings.max_replies_per_day = max(1, min(max_replies_per_day, 200))

        try:
            db.session.commit()
            flash('Налаштування авто-відповідача збережено', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Не вдалося зберегти налаштування: {e}', 'error')

        return redirect(url_for('messaging'))


    @app.route('/invite-campaign/settings', methods=['POST'])
    @login_required
    def invite_campaign_save_settings():
        """Save automated invite campaign program settings."""
        user_id = current_user.id
        account_id = (request.form.get('account_id') or '').strip()
        if not account_id:
            flash('Оберіть акаунт для програми запрошень', 'error')
            return redirect(url_for('messaging'))

        account = InstagramAccount.query.filter_by(id=account_id, user_id=user_id).first()
        if not account:
            flash('Акаунт не знайдено', 'error')
            return redirect(url_for('messaging'))

        enabled = bool(request.form.get('enabled'))
        audience_type = (request.form.get('audience_type') or 'target').strip()[:50]
        stop_on_inbound_reply = bool(request.form.get('stop_on_inbound_reply'))

        def _get_int(name, default):
            try:
                value = int(request.form.get(name, default))
            except Exception:
                value = default
            return value

        max_sends_per_day = _get_int('max_sends_per_day', 20)
        min_delay_seconds = _get_int('min_delay_seconds', 45)
        max_delay_seconds = _get_int('max_delay_seconds', 75)

        step1 = (request.form.get('step1') or '').strip()
        step2 = (request.form.get('step2') or '').strip()
        step3 = (request.form.get('step3') or '').strip()
        step2_offset_hours = _get_int('step2_offset_hours', 48)
        step3_offset_hours = _get_int('step3_offset_hours', 120)

        steps = []
        if step1:
            steps.append({'offset_hours': 0, 'template': step1})
        if step2:
            steps.append({'offset_hours': max(1, int(step2_offset_hours)), 'template': step2})
        if step3:
            steps.append({'offset_hours': max(1, int(step3_offset_hours)), 'template': step3})

        settings = InviteCampaignSettings.query.filter_by(user_id=user_id, instagram_account_id=account_id).first()
        if settings is None:
            settings = InviteCampaignSettings(user_id=user_id, instagram_account_id=account_id)
            db.session.add(settings)

        settings.enabled = enabled
        settings.audience_type = audience_type or 'target'
        settings.max_sends_per_day = max(1, min(max_sends_per_day, 500))
        settings.min_delay_seconds = max(1, min(min_delay_seconds, 3600))
        settings.max_delay_seconds = max(1, min(max_delay_seconds, 3600))
        settings.stop_on_inbound_reply = stop_on_inbound_reply
        settings.steps = steps

        try:
            db.session.commit()
            flash('Налаштування програми запрошень збережено', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Не вдалося зберегти налаштування: {e}', 'error')

        return redirect(url_for('messaging'))
    
    @app.route('/send-messages', methods=['POST'])
    @login_required
    def send_messages():
        """🚀 Відправка повідомлень в Direct"""
        import time
        import random
        
        user_id = current_user.id
        
        # Отримуємо параметри
        account_id = request.form.get('account_id')
        audience_type = request.form.get('audience', 'target')
        limit = int(request.form.get('limit', 10))
        delay = int(request.form.get('delay', 45))
        message_template = request.form.get('message', '').strip()
        
        if not account_id or not message_template:
            flash('Оберіть акаунт та введіть повідомлення', 'error')
            return redirect(url_for('messaging'))
        
        # Перевірка ліміту
        from datetime import date
        today = date.today()
        messages_sent_today = SentMessage.query.filter(
            SentMessage.user_id == user_id,
            db.func.date(SentMessage.sent_at) == today
        ).count()
        
        daily_limit = 20
        remaining = daily_limit - messages_sent_today
        
        if remaining <= 0:
            flash('❌ Денний ліміт вичерпано! Спробуйте завтра.', 'error')
            return redirect(url_for('messaging'))
        
        limit = min(limit, remaining)
        
        # Отримуємо акаунт
        account = InstagramAccount.query.filter_by(id=account_id, user_id=user_id).first()
        if not account:
            flash('Акаунт не знайдено', 'error')
            return redirect(url_for('messaging'))
        
        # Отримуємо аудиторію
        if audience_type == 'target':
            followers = Follower.query.filter_by(user_id=user_id, is_target_audience=True)
        elif audience_type == 'frankfurt':
            followers = Follower.query.filter_by(user_id=user_id, is_frankfurt_region=True)
        else:
            followers = Follower.query.filter_by(user_id=user_id)
        
        # Виключаємо тих, кому вже писали
        sent_usernames = db.session.query(SentMessage.recipient_username).filter_by(user_id=user_id).all()
        sent_set = {s[0] for s in sent_usernames}
        
        recipients = followers.filter(~Follower.username.in_(sent_set)).limit(limit).all()
        
        if not recipients:
            flash('⚠️ Немає нових отримувачів для розсилки', 'warning')
            return redirect(url_for('messaging'))
        
        # Створюємо лог розсилки
        message_log = MessageLog(
            user_id=user_id,
            account_id=account_id,
            account_username=account.instagram_username,
            message_template=message_template,
            audience_type=audience_type,
            status='running'
        )
        db.session.add(message_log)
        db.session.commit()
        
        # Логін в Instagram
        try:
            decrypted_pwd = decrypt_password(account.instagram_password)
            service = InstagramService(account.instagram_username, decrypted_pwd)
            success, login_msg = service.login()
            
            if not success:
                message_log.status = 'error'
                message_log.error_message = login_msg
                db.session.commit()
                flash(f'❌ Помилка входу: {login_msg}', 'error')
                return redirect(url_for('messaging'))
                
        except Exception as e:
            message_log.status = 'error'
            message_log.error_message = str(e)
            db.session.commit()
            flash(f'❌ Помилка: {str(e)}', 'error')
            return redirect(url_for('messaging'))
        
        # Відправляємо повідомлення
        successful = 0
        failed = 0
        
        for i, follower in enumerate(recipients):
            try:
                # Персоналізація
                personalized_msg = message_template.replace('{name}', follower.full_name or follower.username)
                personalized_msg = personalized_msg.replace('{username}', f'@{follower.username}')
                
                # Відправка
                result = service.send_direct_message(follower.username, personalized_msg)
                
                if result.get('success'):
                    successful += 1
                    status = 'sent'
                    error = None
                else:
                    failed += 1
                    status = 'failed'
                    error = result.get('error', 'Unknown error')
                
                # Зберігаємо
                sent_msg = SentMessage(
                    user_id=user_id,
                    message_log_id=message_log.id,
                    recipient_username=follower.username,
                    recipient_user_id=follower.instagram_user_id,
                    status=status,
                    error_message=error
                )
                db.session.add(sent_msg)
                
                # Затримка між повідомленнями (випадкова для природності)
                if i < len(recipients) - 1:
                    actual_delay = delay + random.randint(-10, 15)
                    time.sleep(max(30, actual_delay))
                    
            except Exception as e:
                failed += 1
                sent_msg = SentMessage(
                    user_id=user_id,
                    message_log_id=message_log.id,
                    recipient_username=follower.username,
                    status='failed',
                    error_message=str(e)
                )
                db.session.add(sent_msg)
                
                # Якщо забанили - зупиняємось
                if 'feedback_required' in str(e).lower() or 'challenge' in str(e).lower():
                    message_log.status = 'stopped'
                    message_log.error_message = 'Instagram обмежив дії. Зачекайте 24-48 годин.'
                    break
        
        # Оновлюємо лог
        message_log.total_sent = successful + failed
        message_log.successful = successful
        message_log.failed = failed
        message_log.status = 'completed' if message_log.status != 'stopped' else 'stopped'
        message_log.completed_at = datetime.utcnow()
        db.session.commit()
        
        if message_log.status == 'stopped':
            flash(f'⚠️ Розсилку зупинено! Відправлено: {successful}, помилок: {failed}. Instagram обмежив дії.', 'warning')
        else:
            flash(f'✅ Розсилка завершена! Відправлено: {successful}, помилок: {failed}', 'success')
        
        return redirect(url_for('messaging'))
    
    # ============ AI ASSISTANT ROUTES ============
    
    @app.route('/ai')
    @login_required
    def ai_assistant():
        """🤖 AI Асистент - головна сторінка"""
        from flask import session as flask_session

        requested_tab = request.args.get('tab', 'analyze')
        if requested_tab not in {'analyze', 'generate', 'content', 'trends'}:
            requested_tab = 'analyze'

        # Прибираємо великі payload'и зі session (cookie) щоб не перевищувати ліміт браузера
        flask_session.pop('ai_trends', None)
        flask_session.pop('ai_content_ideas', None)

        # Тренди з БД (сервер-сайд), щоб не зберігати в session
        trends = (RssTrend.query
                  .filter_by(user_id=current_user.id)
                  .order_by(RssTrend.fetched_at.desc())
                  .limit(10)
                  .all())

        trends_for_ideas = [
            {
                'title': t.title,
                'link': t.link,
                'content': t.content or '',
                'published': t.published_at,
                'source': t.source,
                'category': t.category,
                'language': t.language,
                'matched_keywords': t.matched_keywords or [],
                'relevance_score': t.relevance_score or 0,
            }
            for t in trends
        ]
        content_ideas = generate_content_ideas_from_trends(trends_for_ideas) if trends_for_ideas else None

        # AI результати з БД (не в cookie-session)
        def _latest_cache(kind: str):
            row = (AiCache.query
                   .filter_by(user_id=current_user.id, kind=kind)
                   .order_by(AiCache.created_at.desc())
                   .first())
            return row.payload if row and row.payload else None

        settings = AutomationSettings.query.filter_by(user_id=current_user.id).first()

        return render_template('ai_assistant.html',
            ai_available=bool(OPENAI_API_KEY),
            active_tab=requested_tab,
            analysis_results=_latest_cache('analysis'),
            generated_messages=_latest_cache('message'),
            generated_content=_latest_cache('content'),
            trends=trends,
            content_ideas=content_ideas,
            automation_settings=settings
        )
    
    @app.route('/ai/analyze', methods=['POST'])
    @login_required
    def ai_analyze_profiles():
        """🔍 AI аналіз профілів"""
        from flask import session as flask_session
        import re
        
        limit = int(request.form.get('limit', 20))
        filter_type = request.form.get('filter', 'unanalyzed')
        
        # Отримуємо профілі для аналізу
        query = Follower.query.filter_by(user_id=current_user.id)
        
        if filter_type == 'unanalyzed':
            query = query.filter(Follower.quality_score == 0)
        elif filter_type == 'low_score':
            query = query.filter(Follower.quality_score < 30)
        
        followers = query.limit(limit).all()
        
        if not followers:
            flash('Немає профілів для аналізу', 'warning')
            return redirect(url_for('ai_assistant', tab='analyze'))
        
        # Конвертуємо в dict для AI (і відсікаємо невалідні username)
        username_re = re.compile(r'^[A-Za-z0-9._]{1,30}$')
        profiles = []
        skipped = 0
        for f in followers:
            uname = (f.username or '').strip().lstrip('@')
            if not uname or not username_re.match(uname):
                skipped += 1
                continue
            profiles.append({
                'username': uname,
                'biography': f.biography,
                'followers_count': f.followers_count or 0,
                'posts_count': f.posts_count or 0,
                'is_business': f.is_business or False
            })
        
        if not profiles:
            flash('Немає валідних профілів для аналізу (username не пройшли валідацію)', 'warning')
            return redirect(url_for('ai_assistant', tab='analyze'))

        # Аналізуємо
        results = batch_analyze_profiles(profiles, max_profiles=len(profiles))
        
        # Оновлюємо в базі
        for result in results:
            follower = Follower.query.filter_by(
                user_id=current_user.id,
                username=result['username']
            ).first()
            
            if follower and 'ai_analysis' in result:
                ai = result['ai_analysis']
                follower.quality_score = ai.get('quality_score', 50)
                follower.is_target_audience = ai.get('is_target_audience', True)
        
        db.session.commit()
        
        # Зберігаємо короткий результат в БД, щоб не роздувати cookie-session
        try:
            compact = []
            for r in results[:50]:
                compact.append({
                    'username': r.get('username'),
                    'ai_analysis': r.get('ai_analysis')
                })
            db.session.add(AiCache(user_id=current_user.id, kind='analysis', payload=compact))
            db.session.commit()
        except Exception:
            db.session.rollback()

        extra = f' (пропущено невалідних: {skipped})' if skipped else ''
        flash(f'✅ Проаналізовано {len(results)} профілів!{extra}', 'success')
        
        return redirect(url_for('ai_assistant', tab='analyze'))
    
    @app.route('/ai/generate-message', methods=['POST'])
    @login_required
    def ai_generate_message():
        """✍️ Генерація персоналізованого повідомлення"""
        from flask import session as flask_session
        
        username = request.form.get('username', '').strip().lstrip('@')
        bio = request.form.get('bio', '').strip()
        goal = request.form.get('goal', 'знайомство')
        
        if not username:
            flash('Введіть username', 'error')
            return redirect(url_for('ai_assistant', tab='generate'))
        
        # Генеруємо
        result = generate_personalized_message(
            recipient_username=username,
            recipient_bio=bio,
            message_goal=goal
        )
        
        try:
            db.session.add(AiCache(user_id=current_user.id, kind='message', payload=result))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('✅ Повідомлення згенеровано!', 'success')
        
        return redirect(url_for('ai_assistant', tab='generate'))
    
    @app.route('/ai/generate-content', methods=['POST'])
    @login_required
    def ai_generate_content():
        """📝 Генерація контенту для публікації"""
        from flask import session as flask_session
        
        topic = request.form.get('topic', '').strip()
        post_type = request.form.get('post_type', 'informative')
        
        if not topic:
            flash('Введіть тему', 'error')
            return redirect(url_for('ai_assistant', tab='content'))
        
        # Генеруємо
        result = generate_post_content(topic=topic, post_type=post_type)
        
        try:
            db.session.add(AiCache(user_id=current_user.id, kind='content', payload=result))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('✅ Контент згенеровано!', 'success')
        
        return redirect(url_for('ai_assistant', tab='content'))
    
    @app.route('/ai/trends', methods=['POST'])
    @login_required
    def ai_fetch_trends():
        """📰 Отримання трендів з RSS"""
        from flask import session as flask_session

        # Гарантовано чистимо старі великі поля з cookie-based session
        flask_session.pop('ai_trends', None)
        flask_session.pop('ai_content_ideas', None)

        trends = get_trending_topics(days=14, max_topics=10)
        if not trends:
            flash('Не вдалося завантажити тренди з RSS', 'warning')
            return redirect(url_for('ai_assistant', tab='trends'))

        try:
            now = datetime.utcnow()
            links = [t.get('link') for t in trends if t.get('link')]

            existing_by_link = {}
            if links:
                existing = (RssTrend.query
                            .filter(RssTrend.user_id == current_user.id, RssTrend.link.in_(links))
                            .all())
                existing_by_link = {row.link: row for row in existing if row.link}

            saved = 0
            for trend in trends:
                link = trend.get('link')
                row = existing_by_link.get(link) if link else None

                if row is None:
                    row = RssTrend(
                        user_id=current_user.id,
                        title=trend.get('title', 'No title')[:500]
                    )
                    db.session.add(row)
                    saved += 1

                row.content = (trend.get('content') or '')
                row.link = link
                row.source = trend.get('source')
                row.category = trend.get('category')
                row.language = trend.get('language')
                row.image_url = trend.get('image_url')
                row.matched_keywords = trend.get('matched_keywords') or []
                row.relevance_score = int(trend.get('relevance_score') or 0)
                row.published_at = trend.get('published')
                row.fetched_at = now

            db.session.commit()
            flash(f'✅ Завантажено {len(trends)} трендів (нових: {saved})!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Помилка збереження трендів: {e}', 'error')

        return redirect(url_for('ai_assistant', tab='trends'))

    @app.route('/ai/trends/<trend_id>/create-draft', methods=['POST'])
    @login_required
    def ai_create_draft_from_trend(trend_id: str):
        """📝 Створити чернетку поста з RSS тренду (саммарі + CTA)."""
        from flask import session as flask_session

        trend = RssTrend.query.filter_by(id=trend_id, user_id=current_user.id).first()
        if not trend:
            flash('Тренд не знайдено', 'error')
            return redirect(url_for('ai_assistant', tab='trends'))

        # AI саммарі
        summary = summarize_trend(trend.title, trend.content or '')
        summary_text = (summary.get('summary') or '').strip() or trend.title
        relevance_text = (summary.get('relevance') or '').strip()

        # Базові хештеги + трохи з ключових слів
        hashtags = ['#fliesen', '#badsanierung', '#frankfurt', '#bathroom', '#renovierung', '#interiordesign']
        for kw in (trend.matched_keywords or [])[:6]:
            clean = ''.join(ch for ch in str(kw) if ch.isalnum() or ch in ['_', '-'])
            if not clean:
                continue
            tag = '#' + clean.lower().replace('-', '').replace('_', '')
            if tag not in hashtags and len(tag) <= 30:
                hashtags.append(tag)

        cta = (
            "\n\n📩 Хочете сучасну ванну кімнату у Франкфурті та околицях? "
            "Напишіть нам — зробимо безкоштовну консультацію та розрахунок."
        )
        caption_parts = [f"🔥 {trend.title}", summary_text]
        if relevance_text:
            caption_parts.append(relevance_text)
        caption = "\n\n".join([p for p in caption_parts if p]) + cta

        idea = ContentIdea(
            user_id=current_user.id,
            trend_id=trend.id,
            title=trend.title,
            caption=caption,
            hashtags=hashtags,
            content_type='trend_based',
            status='draft',
            generated_image_url=trend.image_url
        )

        try:
            db.session.add(idea)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Не вдалося створити чернетку: {e}', 'error')
            return redirect(url_for('ai_assistant', tab='trends'))

        # Показуємо результат у вкладці "Контент"
        payload = {
            'hook': f"🔥 {trend.title}",
            'caption': caption,
            'hashtags': hashtags,
            'content_ideas': [
                'Використати фото зі статті (якщо доступно) або зробити схожу візуалізацію',
                'Зробити карусель: тренд → приклад → CTA',
                'Зняти коротке відео-пояснення 10–15 сек'
            ]
        }
        try:
            db.session.add(AiCache(user_id=current_user.id, kind='content', payload=payload))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('✅ Чернетку створено! Перейдіть у вкладку "Контент для постів".', 'success')
        return redirect(url_for('ai_assistant', tab='content'))

    @app.route('/ai/automation-settings', methods=['POST'])
    @login_required
    def ai_update_automation_settings():
        """⚙️ Налаштування автоматизації RSS → чернетки → авто-публікація."""
        enabled = bool(request.form.get('enabled'))
        auto_publish = bool(request.form.get('auto_publish'))
        use_animation = bool(request.form.get('use_animation'))

        try:
            animation_duration_seconds = int(request.form.get('animation_duration_seconds', 8))
        except Exception:
            animation_duration_seconds = 8

        try:
            interval = int(request.form.get('rss_check_interval_minutes', 240))
        except Exception:
            interval = 240

        publish_times_raw = (request.form.get('publish_times', '') or '').strip()
        publish_times = []
        if publish_times_raw:
            for part in publish_times_raw.split(','):
                t = part.strip()
                if t:
                    publish_times.append(t)

        timezone_name = (request.form.get('timezone', 'Europe/Berlin') or 'Europe/Berlin').strip()

        try:
            max_posts_per_day = int(request.form.get('max_posts_per_day', 2))
        except Exception:
            max_posts_per_day = 2

        settings = AutomationSettings.query.filter_by(user_id=current_user.id).first()
        if settings is None:
            settings = AutomationSettings(user_id=current_user.id)
            db.session.add(settings)

        settings.enabled = enabled
        settings.auto_publish = auto_publish
        settings.use_animation = use_animation
        settings.rss_check_interval_minutes = max(15, min(interval, 24 * 60))
        settings.publish_times = publish_times or ["09:00", "18:00"]
        settings.timezone = timezone_name
        settings.max_posts_per_day = max(1, min(max_posts_per_day, 10))

        # Optional music file upload
        music_file = request.files.get('music_file')
        if music_file and music_file.filename:
            filename = (music_file.filename or '').strip()
            _, ext = os.path.splitext(filename)
            ext = (ext or '').lower()
            allowed = {'.mp3', '.wav', '.m4a', '.aac'}
            if ext not in allowed:
                flash('❌ Непідтримуваний формат музики. Дозволено: mp3, wav, m4a, aac', 'error')
                return redirect(url_for('ai_assistant', tab='trends'))

            music_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'music')
            os.makedirs(music_dir, exist_ok=True)
            stored_name = f"music_{uuid.uuid4().hex}{ext}"
            full_path = os.path.join(music_dir, stored_name)
            music_file.save(full_path)
            # store repo-relative path
            settings.music_file_path = os.path.join('uploads', 'music', stored_name)

        settings.animation_duration_seconds = max(3, min(animation_duration_seconds, 60))
        settings.animation_fps = 30

        try:
            db.session.commit()
            flash('✅ Налаштування автоматизації збережено', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Не вдалося зберегти налаштування: {e}', 'error')

        return redirect(url_for('ai_assistant', tab='trends'))
    
    # ============ ERROR HANDLERS ============
    
    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def server_error(e):
        return render_template('500.html'), 500
    
    return app


# Создаём экземпляр приложения для импорта и gunicorn
app = create_app()

# Запуск приложения
if __name__ == '__main__':
    # Инициализация базы данных при локальном запуске
    init_db(app)
    
    # Создать папку для uploads
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)
    
    print("Запуск Instagram OSINT приложения...")
    print(f"Сервер: http://127.0.0.1:{os.environ.get('PORT', 5000)}")
    
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=app.config['DEBUG']
    )
