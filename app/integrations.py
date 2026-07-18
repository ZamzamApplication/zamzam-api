from cryptography.fernet import Fernet, InvalidToken
from hashlib import sha256
from base64 import urlsafe_b64encode

from app.config import settings
from app.models import Tahfiz


def _cipher() -> Fernet:
    key = urlsafe_b64encode(sha256(settings.INTEGRATION_ENCRYPTION_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("تعذر قراءة مفتاح التكامل المحفوظ") from exc


def tenant_whatsend_config(tahfiz: Tahfiz) -> tuple[str, str, str]:
    """Return tenant URL, groups URL and API key.

    Global values remain a migration fallback for the original installation.
    Newly configured tenants always use their own encrypted key.
    """
    api_url = tahfiz.whatsend_api_url or settings.WHATSEND_API_URL
    groups_url = tahfiz.whatsend_groups_url or settings.WHATSEND_API_GROUPS_URL
    if not groups_url:
        groups_url = api_url.rsplit("/", 1)[0] + "/groups"
    api_key = decrypt_secret(tahfiz.whatsend_api_key_encrypted) or settings.WHATSEND_API_KEY
    return api_url, groups_url, api_key
