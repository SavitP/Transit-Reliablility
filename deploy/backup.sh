#!/usr/bin/env bash
# Save a copy of the database, keeping the last 7 days. Run daily from cron (see DEPLOY.md).
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUP_DIR="$HOME/backups"
mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/transit-$(date +%Y-%m-%d).dump"

# -Fc = Postgres's compressed "custom" format, which pg_restore can read.
docker compose exec -T db pg_dump -U transit -d transit -Fc > "$FILE.partial"
mv "$FILE.partial" "$FILE"         # only a complete dump gets the real name
find "$BACKUP_DIR" -name 'transit-*.dump' -mtime +7 -delete
echo "Saved $FILE ($(du -h "$FILE" | cut -f1))"
