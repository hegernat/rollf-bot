#!/bin/bash

set -e

PROJECT_DIR="/opt/bots/rollf-bot"
DB_FILE="$PROJECT_DIR/bot.db"
BACKUP_DIR="$PROJECT_DIR/backups"
LOG_FILE="$BACKUP_DIR/backup.log"

DATE=$(date +"%Y%m%d_%H%M")
TMP_BACKUP="$BACKUP_DIR/database_$DATE.db"
FINAL_BACKUP="$TMP_BACKUP.gz"

echo "[$(date)] Starting backup..." >> "$LOG_FILE"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Force WAL checkpoint (flush -wal into main DB)
sqlite3 "$DB_FILE" "PRAGMA wal_checkpoint(FULL);" >> "$LOG_FILE" 2>&1

# Copy DB safely
cp "$DB_FILE" "$TMP_BACKUP"

# Compress backup
gzip "$TMP_BACKUP"

echo "[$(date)] Backup created: $FINAL_BACKUP" >> "$LOG_FILE"

# Rotation: delete backups older than 90 days
find "$BACKUP_DIR" -type f -name "database_*.db.gz" -mtime +180 -delete

echo "[$(date)] Rotation complete." >> "$LOG_FILE"
echo "--------------------------------------" >> "$LOG_FILE"
