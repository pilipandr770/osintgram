"""
Модуль шифрування для безпечного зберігання паролів Instagram.
Використовує Fernet (симетричне шифрування).
"""
import os
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode, urlsafe_b64decode
import hashlib


def get_encryption_key() -> bytes:
    """
    Отримати ключ шифрування з змінної оточення або створити новий.
    
    Returns:
        bytes: Ключ Fernet
    """
    key = os.environ.get('ENCRYPTION_KEY')
    
    if key:
        # Якщо ключ є в змінних оточення
        return key.encode() if isinstance(key, str) else key
    
    # Генеруємо ключ з SECRET_KEY (якщо ENCRYPTION_KEY не заданий)
    secret_key = os.environ.get('SECRET_KEY', 'default-secret-key-change-me')
    # Створюємо 32-байтний ключ з SECRET_KEY
    hashed = hashlib.sha256(secret_key.encode()).digest()
    return urlsafe_b64encode(hashed)


def encrypt_password(password: str) -> str:
    """
    Зашифрувати пароль.
    
    Args:
        password: Пароль у відкритому вигляді
        
    Returns:
        str: Зашифрований пароль (base64)
    """
    if not password:
        return ""
    
    key = get_encryption_key()
    fernet = Fernet(key)
    encrypted = fernet.encrypt(password.encode())
    return encrypted.decode()


def decrypt_password(encrypted_password: str) -> str:
    """
    Розшифрувати пароль.
    
    Args:
        encrypted_password: Зашифрований пароль
        
    Returns:
        str: Пароль у відкритому вигляді
    """
    if not encrypted_password:
        return ""
    
    try:
        key = get_encryption_key()
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_password.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"⚠️ Помилка розшифрування: {e}")
        # Якщо не вдалося розшифрувати - можливо пароль ще не зашифрований
        return encrypted_password
