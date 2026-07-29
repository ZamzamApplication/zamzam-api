from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return naive UTC for compatibility with existing SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
