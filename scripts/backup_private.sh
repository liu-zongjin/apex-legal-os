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
STAMP="$(date '+%Y%m%d-%H%M%S')"

mkdir -p "$BACKUP_DIR/databases" "$BACKUP_DIR/uploads" "$BACKUP_DIR/logs"

if [ -f "$PROJECT_DIR/legal_kb.db" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$PROJECT_DIR/legal_kb.db" ".backup '$BACKUP_DIR/databases/legal_kb-$STAMP.db'"
  else
    cp "$PROJECT_DIR/legal_kb.db" "$BACKUP_DIR/databases/legal_kb-$STAMP.db"
  fi
fi

if [ "$(date '+%u')" = "7" ] && [ -d "$PROJECT_DIR/uploads" ]; then
  tar -czf "$BACKUP_DIR/uploads/uploads-$STAMP.tar.gz" uploads
fi

find "$BACKUP_DIR/databases" -type f -name 'legal_kb-*.db' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR/uploads" -type f -name 'uploads-*.tar.gz' -mtime +60 -delete

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] backup complete"
  echo "project=$PROJECT_DIR"
  echo "backup_dir=$BACKUP_DIR"
} >> "$BACKUP_DIR/logs/backup.log"
