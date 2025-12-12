"""
Main Flask application for Instagram OSINT.
Contains all routes for dashboard, accounts, parsing, followers, export, and publishing.
"""
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from config import config
from database import db, init_db
from models import User, InstagramAccount, Follower, ParseSession, PublishedContent, ExportHistory
from instagram_service import InstagramService
from encryption import encrypt_password, decrypt_password
from geo_search import analyze_profile_relevance, HASHTAGS_SEARCH
from auth import auth_bp
import os
from datetime import datetime
from io import BytesIO, StringIO
import csv
from dotenv import load_dotenv

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
            print(f"✅ Schema '{SCHEMA_NAME}' создана или уже существует")
        
        # Затем создаём таблицы
        db.create_all()
        print(f"✅ Все таблицы созданы в schema '{SCHEMA_NAME}'")
    
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
            db.session.delete(account)
            db.session.commit()
            flash(f'Аккаунт @{account.instagram_username} удален', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка удаления: {str(e)}', 'error')
        
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
            follower = Follower(
                user_id=current_user.id,
                parse_session_id=parse_session.id,
                instagram_user_id=username,  # Используем username как временный ID
                username=username,
                source_account_username=source_account,
                collected_at=datetime.utcnow()
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
                
                # Сохранить файлы временно
                temp_paths = []
                for file in files:
                    if file.filename:
                        filename = f"temp_{datetime.now().timestamp()}_{file.filename}"
                        filepath = os.path.join(upload_folder, filename)
                        file.save(filepath)
                        temp_paths.append(filepath)
                
                # Опубликовать
                if content_type == 'post' and len(temp_paths) == 1:
                    is_success, result = service.publish_post(caption, temp_paths[0])
                elif content_type == 'story':
                    is_success, result = service.publish_story(temp_paths[0])
                elif content_type == 'carousel' and len(temp_paths) > 1:
                    is_success, result = service.publish_carousel(caption, temp_paths)
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
    
    print("🚀 Запуск Instagram OSINT приложения...")
    print(f"📍 Сервер: http://127.0.0.1:{os.environ.get('PORT', 5000)}")
    
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=app.config['DEBUG']
    )
