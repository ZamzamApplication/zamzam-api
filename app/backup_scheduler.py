import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.backup import create_backup, prune_backups
from app.config import settings

logger = logging.getLogger(__name__)


async def backup_loop() -> None:
    interval = max(settings.BACKUP_INTERVAL_HOURS, 1) * 3600
    while True:
        try:
            backup_dir = Path(settings.BACKUP_DIR)
            latest = max(backup_dir.glob("zamzam-*.tar.gz"), key=lambda path: path.stat().st_mtime, default=None)
            age = (
                datetime.now(timezone.utc).timestamp() - latest.stat().st_mtime
                if latest
                else interval
            )
            if age >= interval:
                backup = await asyncio.to_thread(create_backup)
                removed = await asyncio.to_thread(prune_backups)
                logger.info("Created verified backup %s; pruned %s expired backups", backup, removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled backup failed")
        await asyncio.sleep(interval)
