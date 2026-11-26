#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

. "$PROJECT_DIR/scripts/private_env.sh" || exit 1

BACKUP_DIR="${LEGAL_KB_BACKUP_DIR:-$HOME/LegalKBBackups}"
RETENTION_DAYS="${LEGAL_KB_BACKUP_RETENTION_DAYS:-14}"
UPLOAD_DAY=7
if [ -f "$BACKUP_DIR/backup-settings.json" ]; then
  CONFIG_VALUES="$(python3 - "$BACKUP_DIR/backup-settings.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as file:
    settings = json.load(file)
value = settings.get('retention_days', 14)
if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 365:
    raise SystemExit('Invalid backup retention setting')
frequency = settings.get('frequency', 'daily')
if frequency not in ('daily', 'weekdays', 'weekly'):
    raise SystemExit('Invalid backup frequency')
print(value, {'daily': 7, 'weekdays': 5, 'weekly': 0}[frequency])
PY
)"
  read -r RETENTION_DAYS UPLOAD_DAY <<< "$CONFIG_VALUES"
fi
STAMP="$(date '+%Y%m%d-%H%M%S')"

umask 077
mkdir -p "$BACKUP_DIR/databases" "$BACKUP_DIR/uploads" "$BACKUP_DIR/logs"
DB_PATH="${LEGAL_KB_DB_PATH:-${LEGAL_KB_RUNTIME_DIR:-$PROJECT_DIR}/legal_kb.db}"
UPLOAD_DIR="${LEGAL_KB_UPLOAD_DIR:-${LEGAL_KB_RUNTIME_DIR:-$PROJECT_DIR}/uploads}"
if [ -n "${LEGAL_KB_RUNTIME_DIR:-}" ] && [ ! -s "$DB_PATH" ]; then
  printf 'Configured private runtime database is missing or empty\n' >&2
  exit 1
fi
db_stage=
upload_stage=
cleanup_staging() {
  if [ -n "$db_stage" ]; then rm -f -- "$db_stage" "$db_stage-wal" "$db_stage-shm" "$db_stage-journal"; fi
  if [ -n "$upload_stage" ]; then rm -f -- "$upload_stage"; fi
}
trap cleanup_staging EXIT

publish_backup() {
  mv -n -- "$1" "$2"
  if [ -e "$1" ]; then
    echo "Backup already exists: $2" >&2
    return 1
  fi
}

if [ -s "$DB_PATH" ]; then
  db_stage="$(mktemp "$BACKUP_DIR/databases/.staging.XXXXXXXX")"
  python3 - "$DB_PATH" "$db_stage" <<'BACKUP_PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

source_uri = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(source_uri, uri=True)) as source:
    with closing(sqlite3.connect(sys.argv[2])) as target:
        source.backup(target)
        if target.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise SystemExit("Could not finalize the database backup")
        if target.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise SystemExit("Database backup verification failed")
BACKUP_PY
  publish_backup "$db_stage" "$BACKUP_DIR/databases/legal_kb-$STAMP.db"
  find "$BACKUP_DIR/databases" -type f -name 'legal_kb-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].db' \
    -mtime +"$((RETENTION_DAYS - 1))" -delete
fi

if { [ "$UPLOAD_DAY" = "0" ] || [ "$(date '+%u')" = "$UPLOAD_DAY" ]; } && [ -d "$UPLOAD_DIR" ]; then
  upload_stage="$(mktemp "$BACKUP_DIR/uploads/.staging.XXXXXXXX")"
  tar -czf "$upload_stage" -C "$UPLOAD_DIR" -s ',^\.$,uploads,' -s ',^\./,uploads/,' .
  publish_backup "$upload_stage" "$BACKUP_DIR/uploads/uploads-$STAMP.tar.gz"
  find "$BACKUP_DIR/uploads" -type f -name 'uploads-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].tar.gz' -mtime +60 -delete
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] backup complete"
  echo "project=$PROJECT_DIR"
  echo "backup_dir=$BACKUP_DIR"
} >> "$BACKUP_DIR/logs/backup.log"
