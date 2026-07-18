#!/bin/bash
# Kerya Phase 0: daily backup of habits.db + OpenClaw workspace.
# Keeps 14 daily archives in /root/backups, latest always at fixed names
# so an off-site fetcher can pull them without knowing the date.

set -e

BACKUP_DIR=/root/backups
STAMP=$(date +%Y-%m-%d)
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

# 1. SQLite online backup (safe while bot is running)
python3 - << 'PYEOF'
import sqlite3
src = sqlite3.connect("/data/habits.db")
dst = sqlite3.connect("/root/backups/habits-latest.db")
src.backup(dst)
dst.close()
src.close()
PYEOF

cp "$BACKUP_DIR/habits-latest.db" "$BACKUP_DIR/habits-$STAMP.db"

# 2. Kerya workspace (memory, knowledge, identity) — excludes bulky caches
tar -czf "$BACKUP_DIR/workspace-$STAMP.tar.gz" \
    -C /home/clawd/.openclaw workspace \
    --exclude='workspace/.git' 2>/dev/null || true
cp "$BACKUP_DIR/workspace-$STAMP.tar.gz" "$BACKUP_DIR/workspace-latest.tar.gz"

# 3. Bot runtime state not in git (.env, telethon session, seen-caches)
tar -czf "$BACKUP_DIR/botstate-$STAMP.tar.gz" \
    -C /opt/habits-bot .env data 2>/dev/null || true
cp "$BACKUP_DIR/botstate-$STAMP.tar.gz" "$BACKUP_DIR/botstate-latest.tar.gz"

# 4. Rotation
find "$BACKUP_DIR" -name "habits-2*.db" -mtime +$KEEP_DAYS -delete
find "$BACKUP_DIR" -name "workspace-2*.tar.gz" -mtime +$KEEP_DAYS -delete
find "$BACKUP_DIR" -name "botstate-2*.tar.gz" -mtime +$KEEP_DAYS -delete

echo "$(date -Is) backup ok: $(du -sh $BACKUP_DIR | cut -f1)" >> /var/log/kerya-backup.log
