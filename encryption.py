"""
Модуль шифрування для безпечного зберігання паролів Instagram.
Використовує Fernet (симетричне шифрування).
"""
import os
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode, urlsafe_b64decode
import hashlib
import re


_B64URL_RE = re.compile(r'^[A-Za-z0-9_-]+={0,2}$')


def _looks_like_fernet_token(value: str) -> bool:
    if not value:
        return False
    s = value.strip()
    # Fernet tokens are urlsafe-base64 and typically start with 'gAAAA' (version+timestamp)
    if s.startswith('gAAAA'):
        return True
    if len(s) < 80:
        return False
    if ' ' in s or '\n' in s or '\r' in s or '\t' in s:
        return False
    return bool(_B64URL_RE.match(s))


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
        # Backward-compat: DB may contain plaintext. In that case we silently return it.
        # If it looks like a Fernet token but can't be decrypted (wrong key / corrupted), do NOT return it.
        if _looks_like_fernet_token(encrypted_password):
            err_name = type(e).__name__
            err_msg = str(e) or '(no message)'
            print(f"Помилка розшифрування ({err_name}): {err_msg}")
            return ""
        return encrypted_password
