import asyncio
from cryptography.fernet import Fernet, InvalidToken
from hashlib import sha256
from base64 import urlsafe_b64encode
import ipaddress
import os
import socket
from urllib.parse import urlparse

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


def _is_production() -> bool:
    return settings.APP_ENV.lower() == "production" or bool(os.getenv("FLY_APP_NAME"))


def _validate_resolved_addresses(addresses: set[str]) -> None:
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("عنوان خدمة WhatSend يجب ألا يشير إلى شبكة داخلية")


async def validate_whatsend_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ({"https"} if _is_production() else {"http", "https"}):
        raise ValueError("رابط WhatSend يجب أن يستخدم HTTPS")
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("رابط WhatSend غير صالح")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname not in settings.whatsend_allowed_hosts:
        raise ValueError("مضيف WhatSend غير مسموح")

    if not _is_production() and hostname in {"localhost", "127.0.0.1", "::1"}:
        return url

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        loop = asyncio.get_running_loop()
        records = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM),
        )
        addresses = {record[4][0] for record in records}
    else:
        addresses = {str(literal)}
    _validate_resolved_addresses(addresses)
    return url
