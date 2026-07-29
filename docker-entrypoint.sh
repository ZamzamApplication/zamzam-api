#!/bin/sh
set -eu

for data_dir in /data /app/uploads /app/backups; do
  if [ -e "$data_dir" ]; then
    chown -R zamzam:zamzam "$data_dir"
  fi
done

exec gosu zamzam "$@"
