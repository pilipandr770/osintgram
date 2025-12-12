# Instagram OSINT Flask Application

📸 Профессиональное приложение для сбора данных подписчиков конкурентов в Instagram.

## 🚀 Функциональность

- ✅ Регистрация/Вход пользователей
- ✅ Добавление Instagram аккаунтов для управления
- ✅ Парсинг подписчиков конкурентов
- ✅ Извлечение контактов из биографии (email, phone, website)
- ✅ Quality Score для оценки контактов
- ✅ Фильтрация и пагинация подписчиков
- ✅ Экспорт в CSV для Meta Ads Custom Audience
- ✅ Публикация контента (посты, истории, карусели)
- ✅ История парсинга и статистика

## 📋 Требования

- Python 3.9+
- PostgreSQL
- pip

## 🛠 Установка

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/yourusername/instagram-osint.git
cd instagram-osint
```

### 2. Создайте виртуальное окружение

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Установите зависимости

```bash
pip install -r requirements.txt
```

### 4. Настройте переменные окружения

Создайте файл `.env` на основе примера:

```env
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your-super-secret-key-here

# PostgreSQL
DATABASE_URL=postgresql://username:password@localhost:5432/instagram_osint_db
```

### 5. Создайте базу данных

```bash
# Создайте БД в PostgreSQL
createdb instagram_osint_db

# Или через psql
psql -U postgres
CREATE DATABASE instagram_osint_db;
```

### 6. Запустите приложение

```bash
python app.py
```

Откройте http://localhost:5000 в браузере.

## 🌐 Развертывание на Render.com

### 1. Подготовка

Убедитесь, что в репозитории есть:
- `Procfile`
- `runtime.txt`
- `requirements.txt`

### 2. Создание Web Service

1. Зайдите на https://render.com
2. New → Web Service
3. Подключите GitHub репозиторий
4. Настройки:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn "app:create_app()"`

### 3. Добавьте PostgreSQL

1. New → PostgreSQL
2. Скопируйте Internal Database URL
3. Добавьте в Environment Variables Web Service

### 4. Environment Variables

```
FLASK_ENV=production
SECRET_KEY=<generate-with-secrets-module>
DATABASE_URL=<from-postgresql>
```

## 📁 Структура проекта

```
instagram-osint/
├── app.py                    # Главное Flask приложение
├── config.py                 # Конфигурация
├── database.py               # Инициализация SQLAlchemy
├── models.py                 # SQLAlchemy модели
├── instagram_service.py      # Сервис Instagrapi
├── auth.py                   # Аутентификация
├── requirements.txt          # Зависимости
├── Procfile                  # Для Render.com
├── runtime.txt               # Версия Python
├── templates/                # HTML шаблоны
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── add_account.html
│   ├── parse_competitors.html
│   ├── followers_table.html
│   ├── publish.html
│   └── statistics.html
├── static/                   # CSS и JS
│   ├── style.css
│   ├── dashboard.css
│   ├── tables.css
│   └── script.js
└── uploads/                  # Временные файлы
```

## 🔐 Безопасность

- Все пароли хешируются с PBKDF2:SHA256
- Session cookies с secure, httponly, samesite флагами
- CSRF защита (рекомендуется добавить Flask-WTF)
- SQL injection защита через SQLAlchemy ORM

## ⚠️ Важные замечания

1. **Пароли Instagram** - рекомендуется шифровать перед хранением
2. **Rate Limits** - Instagram ограничивает количество запросов
3. **Приватные аккаунты** - не парсятся без подписки
4. **Используйте прокси** - для масштабного парсинга

## 📊 Модели базы данных

- **User** - пользователи приложения
- **InstagramAccount** - Instagram аккаунты для парсинга
- **Follower** - собранные подписчики
- **ParseSession** - история сессий парсинга
- **PublishedContent** - история публикаций
- **ExportHistory** - история экспортов

## 🔧 API Instagrapi

Используемые методы:
- `client.login()` - вход
- `client.account_info()` - информация о своем аккаунте
- `client.user_info_by_username()` - информация о пользователе
- `client.user_followers()` - получение подписчиков
- `client.photo_upload()` - публикация поста
- `client.album_upload()` - публикация карусели
- `client.photo_upload_to_story()` - публикация истории

## 📄 Лицензия

MIT License

## 👨‍💻 Автор

Created with ❤️ for Instagram OSINT research.
