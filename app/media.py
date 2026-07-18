from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings


def signed_media_url(path: str | None, tahfiz_id: int) -> str | None:
    if not path or path.startswith(("http://", "https://")):
        return path
    normalized = path.removeprefix("/uploads/").removeprefix("uploads/")
    expires = datetime.now(timezone.utc) + timedelta(minutes=60)
    token = jwt.encode(
        {"type": "media", "path": normalized, "tahfiz_id": tahfiz_id, "exp": expires},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return f"/uploads/{normalized}?token={token}"


def validate_media_token(token: str, path: str) -> int:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired media token") from exc
    if payload.get("type") != "media" or payload.get("path") != path:
        raise ValueError("Invalid media token")
    return int(payload["tahfiz_id"])
