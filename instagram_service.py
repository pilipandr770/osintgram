"""
Instagram Service module for Instagram OSINT application.
Uses Instagrapi library for Instagram API interactions.
"""
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, PleaseWaitFewMinutes, BadPassword, ChallengeRequired,
    TwoFactorRequired, SelectContactPointRecoveryForm, RecaptchaChallengeForm,
    FeedbackRequired, UnknownError, ClientError
)
from database import db
from models import Follower, ParseSession
from datetime import datetime
import logging
import re
import os
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# Папка для сохранения сессий
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), 'sessions')
os.makedirs(SESSIONS_DIR, exist_ok=True)


class InstagramService:
    """Сервис для работы с Instagram через Instagrapi"""
    
    def __init__(self, username: str, password: str, proxy: Optional[Dict] = None):
        """
        Инициализация клиента Instagram
        
        Args:
            username: логин Instagram
            password: пароль Instagram
            proxy: опциональный прокси {'http': 'http://...', 'https': 'https://...'}
        """
        self.client = Client()
        self.client.delay_range = [2, 5]  # Увеличена задержка
        
        # Настройки для обхода блокировок
        self.client.set_locale('ru_RU')
        self.client.set_timezone_offset(3 * 3600)  # Moscow timezone
        
        if proxy:
            self.client.set_proxy(proxy.get('https') or proxy.get('http'))
        
        self.username = username
        self.password = password
        self._logged_in = False
        self.session_file = os.path.join(SESSIONS_DIR, f'{username}_session.json')
    
    def login(self) -> Tuple[bool, str]:
        """
        Вход в аккаунт Instagram с поддержкой сохранения сессии
        
        Returns:
            Tuple[bool, str]: (успех, сообщение)
        """
        # Пробуем загрузить существующую сессию
        if os.path.exists(self.session_file):
            try:
                self.client.load_settings(self.session_file)
                self.client.login(self.username, self.password)
                self._logged_in = True
                print(f"✅ Вход через сохранённую сессию: {self.username}")
                return True, "Успешно вошли через сохранённую сессию"
            except Exception as e:
                print(f"⚠️ Сессия устарела, пробуем обычный вход: {e}")
                os.remove(self.session_file)
        
        # Обычный вход
        try:
            print(f"🔐 Попытка входа: {self.username}")
            self.client.login(self.username, self.password)
            self._logged_in = True
            
            # Сохраняем сессию
            self.client.dump_settings(self.session_file)
            print(f"✅ Успешный вход, сессия сохранена: {self.username}")
            
            return True, "Успешно вошли в аккаунт"
            
        except BadPassword as e:
            print(f"❌ BadPassword для {self.username}: {e}")
            return False, "Неверный пароль. Проверьте правильность пароля."
            
        except TwoFactorRequired:
            print(f"⚠️ 2FA требуется для {self.username}")
            return False, "Включена двухфакторная аутентификация. Отключите 2FA в настройках Instagram или используйте App Password."
            
        except ChallengeRequired as e:
            print(f"⚠️ Challenge для {self.username}: {e}")
            return False, "Instagram требует подтверждение! Откройте Instagram в браузере с этого же компьютера, пройдите проверку, затем попробуйте снова."
            
        except SelectContactPointRecoveryForm:
            print(f"⚠️ Recovery form для {self.username}")
            return False, "Instagram требует подтверждение через email/телефон. Войдите в Instagram через браузер."
            
        except RecaptchaChallengeForm:
            print(f"⚠️ Captcha для {self.username}")
            return False, "Instagram показывает капчу. Войдите в Instagram через браузер и пройдите проверку."
            
        except FeedbackRequired as e:
            print(f"⚠️ Feedback required для {self.username}: {e}")
            return False, "Instagram заблокировал действие. Подождите несколько часов."
            
        except PleaseWaitFewMinutes:
            print(f"⚠️ Rate limit для {self.username}")
            return False, "Слишком много попыток. Подождите 10-15 минут."
            
        except ClientError as e:
            error_msg = str(e)
            print(f"❌ ClientError для {self.username}: {error_msg}")
            
            if 'checkpoint' in error_msg.lower():
                return False, "Instagram требует подтверждение! Откройте приложение Instagram на телефоне."
            elif 'password' in error_msg.lower():
                return False, "Неверный пароль или Instagram заблокировал вход с нового устройства."
            else:
                return False, f"Ошибка Instagram: {error_msg}"
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Общая ошибка для {self.username}: {error_msg}")
            
            # Анализируем текст ошибки
            if 'password' in error_msg.lower() or 'credentials' in error_msg.lower():
                return False, "Проблема с авторизацией. Попробуйте: 1) Войти в Instagram через браузер 2) Подождать 10 мин 3) Попробовать снова"
            elif 'challenge' in error_msg.lower():
                return False, "Требуется подтверждение. Откройте Instagram на телефоне."
            else:
                return False, f"Ошибка входа: {error_msg}"
    
    def get_account_info(self) -> Dict:
        """
        Получить информацию о своем аккаунте
        
        Returns:
            Dict: информация о профиле
        """
        try:
            user_info = self.client.account_info()
            print(f"DEBUG: user_info type = {type(user_info)}")
            print(f"DEBUG: user_info attrs = {dir(user_info)}")
            
            # Пробуем разные варианты атрибутов (зависит от версии instagrapi)
            followers = getattr(user_info, 'follower_count', None) or getattr(user_info, 'followers_count', None) or 0
            following = getattr(user_info, 'following_count', None) or getattr(user_info, 'followees_count', None) or 0
            posts = getattr(user_info, 'media_count', None) or getattr(user_info, 'posts_count', None) or 0
            
            return {
                'user_id': str(user_info.pk),
                'username': user_info.username,
                'full_name': getattr(user_info, 'full_name', '') or '',
                'biography': getattr(user_info, 'biography', '') or '',
                'profile_pic_url': str(user_info.profile_pic_url) if getattr(user_info, 'profile_pic_url', None) else '',
                'followers_count': followers,
                'following_count': following,
                'posts_count': posts,
                'is_verified': getattr(user_info, 'is_verified', False) or False,
                'is_business': getattr(user_info, 'is_business', False) or False,
                'is_private': getattr(user_info, 'is_private', False) or False
            }
        except Exception as e:
            print(f"Error getting account info: {str(e)}")
            # Возвращаем минимальные данные
            return {
                'user_id': self.username,
                'username': self.username,
                'full_name': '',
                'biography': '',
                'profile_pic_url': '',
                'followers_count': 0,
                'following_count': 0,
                'posts_count': 0,
                'is_verified': False,
                'is_business': False,
                'is_private': False
            }
    
    def get_user_info_by_username(self, username: str) -> Optional[Dict]:
        """
        Получить информацию о пользователе по username
        
        Args:
            username: username пользователя
            
        Returns:
            Dict или None: информация о пользователе
        """
        try:
            # Убираем @ если есть
            username = username.lstrip('@').strip()
            user_info = self.client.user_info_by_username(username)
            
            return {
                'user_id': str(user_info.pk),
                'username': user_info.username,
                'full_name': user_info.full_name or '',
                'biography': user_info.biography or '',
                'profile_pic_url': str(user_info.profile_pic_url) if user_info.profile_pic_url else '',
                'followers_count': user_info.follower_count or 0,
                'following_count': user_info.following_count or 0,
                'posts_count': user_info.media_count or 0,
                'is_verified': user_info.is_verified or False,
                'is_business': user_info.is_business or False,
                'is_private': user_info.is_private or False
            }
        except Exception as e:
            logger.error(f"Error getting user info for {username}: {str(e)}")
            return None
    
    def get_followers_from_account(self, target_username: str, max_followers: int = 10000) -> Tuple[List[Dict], str]:
        """
        Получить список подписчиков из целевого аккаунта
        
        Args:
            target_username: username целевого аккаунта
            max_followers: максимальное количество подписчиков для сбора
            
        Returns:
            Tuple[List[Dict], str]: (список подписчиков, сообщение об ошибке или пусто)
        """
        try:
            # Убираем @ если есть
            target_username = target_username.lstrip('@').strip()
            print(f"🔍 Парсинг подписчиков @{target_username}...")
            
            # Получить ID аккаунта через user_id_from_username (более надёжный метод)
            try:
                user_id = self.client.user_id_from_username(target_username)
                user = self.client.user_info(user_id)
            except Exception as e:
                print(f"⚠️ Ошибка получения user_id: {e}")
                return [], f"Не удалось найти аккаунт @{target_username}"
            
            # Проверяем приватность
            if user.is_private:
                return [], f"Аккаунт @{target_username} приватный"
            
            print(f"📊 Аккаунт найден: @{target_username} ({user.follower_count} подписчиков)")
            
            # Получить подписчиков
            print(f"⏳ Собираем до {max_followers} подписчиков...")
            followers = self.client.user_followers(user_id, amount=max_followers)
            print(f"✅ Получено {len(followers)} подписчиков")
            
            followers_data = []
            for idx, (follower_pk, follower) in enumerate(followers.items()):
                if idx % 50 == 0:
                    print(f"📝 Обработано {idx}/{len(followers)} подписчиков...")
                    
                # Используем базовую информацию (без детального запроса для скорости)
                follower_dict = {
                    'instagram_user_id': str(follower_pk),
                    'username': follower.username,
                    'full_name': follower.full_name or '',
                    'biography': '',
                    'profile_pic_url': str(follower.profile_pic_url) if follower.profile_pic_url else '',
                    'followers_count': 0,
                    'following_count': 0,
                    'posts_count': 0,
                    'is_verified': getattr(follower, 'is_verified', False) or False,
                    'is_business': False,
                    'is_private': getattr(follower, 'is_private', False) or False,
                    'source_account_username': target_username,
                }
                
                # Парсим контакты из биографии (пока пусто)
                follower_dict.update({
                    'email': None,
                    'phone': None,
                    'website_url': None,
                    'tags_from_bio': []
                })
                
                # Базовый score
                follower_dict['quality_score'] = 50
                
                followers_data.append(follower_dict)
            
            print(f"✅ Собрано {len(followers_data)} подписчиков из @{target_username}")
            return followers_data, ""
            
        except Exception as e:
            error_msg = f"Ошибка при сборе подписчиков @{target_username}: {str(e)}"
            print(f"❌ {error_msg}")
            return [], error_msg
    
    def parse_competitors(self, competitor_usernames: List[str], parse_session_id: str, 
                          user_id: str, max_followers: int = 10000) -> Tuple[int, Dict]:
        """
        Парсить подписчиков нескольких конкурентов
        
        Args:
            competitor_usernames: список username конкурентов
            parse_session_id: ID сессии парсинга
            user_id: ID пользователя приложения
            max_followers: максимальное количество подписчиков для сбора с каждого аккаунта
            
        Returns:
            Tuple[int, Dict]: (общее количество собранных, словарь ошибок)
        """
        total_collected = 0
        failed_accounts = {}
        unique_usernames = set()
        
        for competitor_username in competitor_usernames:
            competitor_username = competitor_username.lstrip('@').strip()
            
            if not competitor_username:
                continue
                
            try:
                followers_data, error = self.get_followers_from_account(competitor_username, max_followers)
                
                if error:
                    failed_accounts[competitor_username] = error
                    continue
                
                # Сохранить подписчиков в БД
                for follower_data in followers_data:
                    # Проверить не существует ли уже такой подписчик
                    existing = Follower.query.filter_by(
                        user_id=user_id,
                        instagram_user_id=follower_data['instagram_user_id']
                    ).first()
                    
                    if not existing:
                        follower = Follower(
                            user_id=user_id,
                            parse_session_id=parse_session_id,
                            **follower_data
                        )
                        db.session.add(follower)
                        unique_usernames.add(follower_data['username'])
                        total_collected += 1
                
                db.session.commit()
                logger.info(f"Saved {len(followers_data)} followers from {competitor_username}")
                
            except Exception as e:
                error_msg = str(e)
                failed_accounts[competitor_username] = error_msg
                logger.error(f"Error parsing {competitor_username}: {error_msg}")
                db.session.rollback()
        
        # Обновить сессию парсинга
        parse_session = ParseSession.query.get(parse_session_id)
        if parse_session:
            parse_session.total_followers_collected = total_collected
            parse_session.unique_followers_count = len(unique_usernames)
            parse_session.failed_accounts = failed_accounts if failed_accounts else None
            parse_session.completed_at = datetime.utcnow()
            parse_session.status = 'completed' if not failed_accounts else 'completed_with_errors'
            
            if parse_session.started_at:
                duration = (parse_session.completed_at - parse_session.started_at).total_seconds()
                parse_session.duration_seconds = int(duration)
            
            db.session.commit()
        
        return total_collected, failed_accounts
    
    def publish_post(self, caption: str, image_path: str) -> Tuple[bool, str]:
        """
        Опубликовать пост
        
        Args:
            caption: текст подписи
            image_path: путь к изображению
            
        Returns:
            Tuple[bool, str]: (успех, ID поста или ошибка)
        """
        try:
            media = self.client.photo_upload(image_path, caption)
            return True, str(media.pk)
        except Exception as e:
            logger.error(f"Error publishing post: {str(e)}")
            return False, str(e)
    
    def publish_story(self, image_path: str) -> Tuple[bool, str]:
        """
        Опубликовать историю
        
        Args:
            image_path: путь к изображению/видео
            
        Returns:
            Tuple[bool, str]: (успех, ответ сервера или ошибка)
        """
        try:
            result = self.client.photo_upload_to_story(image_path)
            return True, str(result.pk) if result else "История опубликована"
        except Exception as e:
            logger.error(f"Error publishing story: {str(e)}")
            return False, str(e)
    
    def publish_carousel(self, caption: str, image_paths: List[str]) -> Tuple[bool, str]:
        """
        Опубликовать карусель (несколько фото)
        
        Args:
            caption: текст подписи
            image_paths: список путей к изображениям
            
        Returns:
            Tuple[bool, str]: (успех, ID поста или ошибка)
        """
        try:
            media = self.client.album_upload(image_paths, caption)
            return True, str(media.pk)
        except Exception as e:
            logger.error(f"Error publishing carousel: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def _extract_contacts_from_bio(bio: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Парсить контакты из биографии
        
        Args:
            bio: биография пользователя
            
        Returns:
            Tuple: (email, phone, website)
        """
        email = None
        phone = None
        website = None
        
        if not bio:
            return email, phone, website
        
        # Email regex
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        email_match = re.search(email_pattern, bio)
        if email_match:
            email = email_match.group()
        
        # Phone regex (международный формат)
        phone_pattern = r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,9}'
        phone_match = re.search(phone_pattern, bio)
        if phone_match:
            phone_candidate = phone_match.group().strip()
            # Фильтруем слишком короткие номера
            if len(re.sub(r'\D', '', phone_candidate)) >= 7:
                phone = phone_candidate
        
        # URL
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        url_match = re.search(url_pattern, bio)
        if url_match:
            website = url_match.group()
        
        return email, phone, website
    
    @staticmethod
    def _extract_tags_from_bio(bio: str) -> List[str]:
        """
        Парсить хэштеги из биографии
        
        Args:
            bio: биография пользователя
            
        Returns:
            List[str]: список уникальных хэштегов
        """
        if not bio:
            return []
        
        hashtag_pattern = r'#[\w\u0400-\u04FF]+'  # Поддержка кириллицы
        tags = re.findall(hashtag_pattern, bio)
        return list(set(tags))  # уникальные теги
    
    @staticmethod
    def _calculate_quality_score(follower_data: Dict) -> int:
        """
        Расчет качественного score подписчика (0-100)
        
        Критерии:
        - Email присутствует: 20 баллов
        - Верифицирован: 15 баллов
        - Заполнено имя: 10 баллов
        - Заполнена биография: 10 баллов
        - Бизнес аккаунт: 20 баллов
        - Много подписчиков (>1000): 15 баллов
        - Много постов (>50): 10 баллов
        
        Args:
            follower_data: данные подписчика
            
        Returns:
            int: score от 0 до 100
        """
        score = 0
        
        # Email присутствует (20 баллов)
        if follower_data.get('email'):
            score += 20
        
        # Верифицирован (15 баллов)
        if follower_data.get('is_verified'):
            score += 15
        
        # Хорошо заполненный профиль
        if follower_data.get('full_name'):
            score += 10
        if follower_data.get('biography'):
            score += 10
        
        # Бизнес аккаунт (20 баллов)
        if follower_data.get('is_business'):
            score += 20
        
        # Активность: много подписчиков (15 баллов)
        if (follower_data.get('followers_count') or 0) > 1000:
            score += 15
        
        # Активность: много постов (10 баллов)
        if (follower_data.get('posts_count') or 0) > 50:
            score += 10
        
        return min(score, 100)
