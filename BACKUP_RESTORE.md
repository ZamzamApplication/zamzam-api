# Backup and restore

The API creates a verified SQLite-and-uploads archive every 24 hours in
`BACKUP_DIR` and retains 14 days by default. Fly Volume daily snapshots provide
a second layer; `fly.toml` requests 30-day retention for newly created volumes.

Create and verify an application backup:

```bash
python -m app.backup create
python -m app.backup verify /data/backups/zamzam-<timestamp>.tar.gz
```

Restore while the API process is stopped:

```bash
python -m app.backup restore /data/backups/zamzam-<timestamp>.tar.gz --confirm
alembic upgrade head
```

The restore command verifies the manifest, checksum, and SQLite integrity first,
then retains a pre-restore database copy.

For a full-volume disaster recovery, list snapshots and create a replacement
volume from the selected snapshot:

```bash
fly volumes list -a zamzam-api
fly volumes snapshots list <volume-id>
fly volumes create zamzam_data --snapshot-id <snapshot-id> -s 1 -a zamzam-api
```

Perform a restore drill at least quarterly using a temporary database or volume.
