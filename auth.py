"""
Authentication module for Instagram OSINT application.
Blueprint with registration, login, logout routes.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from database import db
from models import User
from datetime import datetime
from functools import wraps

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя"""
    # Если уже залогинен - на дашборд
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        company_name = request.form.get('company_name', '').strip()
        
        # Валидация
        errors = []
        
        if not email:
            errors.append('Email обязателен')
        if not username:
            errors.append('Имя пользователя обязательно')
        if not password:
            errors.append('Пароль обязателен')
        
        if password != password_confirm:
            errors.append('Пароли не совпадают')
        
        if len(password) < 8:
            errors.append('Пароль должен быть минимум 8 символов')
        
        if len(username) < 3:
            errors.append('Имя пользователя минимум 3 символа')
        
        # Проверить формат email
        if email and '@' not in email:
            errors.append('Неверный формат email')
        
        # Проверить существует ли пользователь
        if User.query.filter_by(email=email).first():
            errors.append('Email уже зарегистрирован')
        
        if User.query.filter_by(username=username).first():
            errors.append('Имя пользователя уже занято')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('auth.register'))
        
        # Создать пользователя
        try:
            user = User(
                email=email,
                username=username,
                company_name=company_name or None
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при регистрации: {str(e)}', 'error')
            return redirect(url_for('auth.register'))
    
    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему"""
    # Если уже залогинен - на дашборд
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        if not email or not password:
            flash('Введите email и пароль', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Аккаунт деактивирован', 'error')
                return redirect(url_for('auth.login'))
            
            login_user(user, remember=bool(remember))
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            # Редирект на запрошенную страницу или дашборд
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            flash('Неверный email или пароль', 'error')
    
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('auth.login'))


def login_required_custom(f):
    """
    Кастомный декоратор для проверки логина
    с кастомным сообщением
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
