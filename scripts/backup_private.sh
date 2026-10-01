#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env.private" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_DIR/.env.private"
  set +a
fi

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

mkdir -p "$BACKUP_DIR/databases" "$BACKUP_DIR/uploads" "$BACKUP_DIR/logs"

if [ -f "$PROJECT_DIR/legal_kb.db" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$PROJECT_DIR/legal_kb.db" ".backup '$BACKUP_DIR/databases/legal_kb-$STAMP.db'"
  else
    cp "$PROJECT_DIR/legal_kb.db" "$BACKUP_DIR/databases/legal_kb-$STAMP.db"
  fi
fi

if { [ "$UPLOAD_DAY" = "0" ] || [ "$(date '+%u')" = "$UPLOAD_DAY" ]; } && [ -d "$PROJECT_DIR/uploads" ]; then
  tar -czf "$BACKUP_DIR/uploads/uploads-$STAMP.tar.gz" uploads
fi

find "$BACKUP_DIR/databases" -type f -name 'legal_kb-*.db' -mtime +"$((RETENTION_DAYS - 1))" -delete
find "$BACKUP_DIR/uploads" -type f -name 'uploads-*.tar.gz' -mtime +60 -delete

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] backup complete"
  echo "project=$PROJECT_DIR"
  echo "backup_dir=$BACKUP_DIR"
} >> "$BACKUP_DIR/logs/backup.log"
