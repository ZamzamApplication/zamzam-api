"""Consistent SQLite backups with integrity verification and guarded restore."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from app.config import settings


def sqlite_path(database_url: str | None = None) -> Path:
    url = database_url or settings.DATABASE_URL
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError("The built-in backup tool currently supports SQLite only")
    raw = unquote(url[len(prefix):])
    return Path("/" + raw.lstrip("/")) if raw.startswith("/") else Path(raw).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {result}")
    finally:
        connection.close()


def create_backup(
    database_path: Path | None = None,
    upload_dir: Path | None = None,
    backup_dir: Path | None = None,
) -> Path:
    database_path = database_path or sqlite_path()
    upload_dir = upload_dir or Path(settings.UPLOAD_DIR)
    backup_dir = backup_dir or Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"zamzam-{timestamp}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="zamzam-backup-") as temporary:
        temporary_path = Path(temporary)
        database_copy = temporary_path / "quran_tracker.db"
        source = sqlite3.connect(database_path)
        target = sqlite3.connect(database_copy)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        verify_sqlite(database_copy)
        manifest = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_sha256": sha256_file(database_copy),
            "database_file": "quran_tracker.db",
            "uploads_included": upload_dir.exists(),
        }
        manifest_path = temporary_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with tarfile.open(destination, "w:gz") as archive:
            archive.add(database_copy, arcname="quran_tracker.db")
            archive.add(manifest_path, arcname="manifest.json")
            if upload_dir.exists():
                archive.add(upload_dir, arcname="uploads")
    return destination


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError("Backup contains an unsafe path")
    archive.extractall(destination, filter="data")


def verify_backup(backup_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="zamzam-verify-") as temporary:
        temporary_path = Path(temporary)
        with tarfile.open(backup_path, "r:gz") as archive:
            _safe_extract(archive, temporary_path)
        manifest = json.loads((temporary_path / "manifest.json").read_text(encoding="utf-8"))
        database_copy = temporary_path / manifest["database_file"]
        if sha256_file(database_copy) != manifest["database_sha256"]:
            raise RuntimeError("Backup database checksum does not match the manifest")
        verify_sqlite(database_copy)
        return manifest


def restore_backup(
    backup_path: Path,
    database_path: Path | None = None,
    upload_dir: Path | None = None,
) -> None:
    database_path = database_path or sqlite_path()
    upload_dir = upload_dir or Path(settings.UPLOAD_DIR)
    verify_backup(backup_path)
    with tempfile.TemporaryDirectory(prefix="zamzam-restore-") as temporary:
        temporary_path = Path(temporary)
        with tarfile.open(backup_path, "r:gz") as archive:
            _safe_extract(archive, temporary_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        safety_copy = database_path.with_suffix(f".pre-restore-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db")
        if database_path.exists():
            shutil.copy2(database_path, safety_copy)
        shutil.copy2(temporary_path / "quran_tracker.db", database_path)
        restored_uploads = temporary_path / "uploads"
        if restored_uploads.exists():
            if upload_dir.exists():
                shutil.move(str(upload_dir), str(upload_dir.with_name(f"{upload_dir.name}.pre-restore")))
            shutil.copytree(restored_uploads, upload_dir)


def prune_backups(backup_dir: Path | None = None, retention_days: int | None = None) -> int:
    backup_dir = backup_dir or Path(settings.BACKUP_DIR)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days or settings.BACKUP_RETENTION_DAYS)
    removed = 0
    for path in backup_dir.glob("zamzam-*.tar.gz"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("create")
    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("backup", type=Path)
    restore_parser = subcommands.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.command == "create":
        backup = create_backup()
        prune_backups()
        print(backup)
    elif args.command == "verify":
        print(json.dumps(verify_backup(args.backup), indent=2))
    elif args.command == "restore":
        if not args.confirm:
            raise SystemExit("Restore refused: pass --confirm and stop the application first")
        restore_backup(args.backup)
        print("restore complete")


if __name__ == "__main__":
    main()
