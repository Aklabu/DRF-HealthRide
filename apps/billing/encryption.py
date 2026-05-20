"""
Simple symmetric encryption for sensitive fields (bank account numbers).
Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
The encryption key is read from FIELD_ENCRYPTION_KEY in environment variables.
"""
import base64
from django.conf import settings


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
        if not key:
            raise ValueError('FIELD_ENCRYPTION_KEY is not set in settings.')
        # Key must be 32 url-safe base64-encoded bytes
        return Fernet(key.encode() if isinstance(key, str) else key)
    except ImportError:
        return None


def encrypt_field(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64-encoded ciphertext."""
    fernet = _get_fernet()
    if fernet is None:
        # cryptography not installed — store as-is (dev fallback only)
        return plaintext
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext."""
    fernet = _get_fernet()
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ''


def mask_number(number: str, keep_last: int = 4) -> str:
    """Return a masked version of a number string, keeping only the last N digits."""
    number = str(number).strip()
    if len(number) <= keep_last:
        return number
    return '*' * (len(number) - keep_last) + number[-keep_last:]
