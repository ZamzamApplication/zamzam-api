import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.backup import create_backup, restore_backup, verify_backup


class BackupRestoreTests(unittest.TestCase):
    def test_backup_verifies_and_restores_database_and_uploads(self):
        with tempfile.TemporaryDirectory(prefix="zamzam-backup-test-") as temporary:
            root = Path(temporary)
            database = root / "source.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO sample (value) VALUES ('safe')")
            connection.commit()
            connection.close()
            uploads = root / "uploads"
            uploads.mkdir()
            (uploads / "proof.txt").write_text("uploaded", encoding="utf-8")

            backup = create_backup(database, uploads, root / "backups")
            manifest = verify_backup(backup)
            restored_database = root / "restored.db"
            restored_uploads = root / "restored-uploads"
            restore_backup(backup, restored_database, restored_uploads)

            restored = sqlite3.connect(restored_database)
            try:
                value = restored.execute("SELECT value FROM sample").fetchone()[0]
            finally:
                restored.close()
            self.assertEqual(manifest["format"], 1)
            self.assertEqual(value, "safe")
            self.assertEqual((restored_uploads / "proof.txt").read_text(encoding="utf-8"), "uploaded")
