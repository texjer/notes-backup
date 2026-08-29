#!/bin/zsh
# Installs notes-backup: python venv, config, and an hourly launchd agent.
# Usage: ./install.sh [backup_dir]   (default backup_dir: ~/NotesBackup)
set -euo pipefail

PROJECT_DIR="${0:A:h}"
BACKUP_DIR="${1:-$HOME/NotesBackup}"
INTERVAL="${NOTES_BACKUP_INTERVAL:-3600}"   # seconds between runs
CONFIG_DIR="$HOME/.config/notes-backup"
CONFIG="$CONFIG_DIR/config.json"
LABEL="local.notes-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/notes-backup.log"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

echo "==> Setting up Python environment"
if [[ ! -x "$PYTHON" ]]; then
    # --copies gives the venv its own python binary at a stable path,
    # which is what you grant Full Disk Access to.
    python3 -m venv --copies "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/pip" install --quiet --upgrade apple-notes-parser

echo "==> Writing config to $CONFIG"
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG" ]]; then
    cat > "$CONFIG" <<EOF
{
  "backup_dir": "${BACKUP_DIR/#$HOME/~}",
  "db_snapshot_tiers": [
    {"every_hours": 6,   "for_days": 2},
    {"every_hours": 24,  "for_days": 7},
    {"every_hours": 720, "for_days": null}
  ],
  "commit_media": true
}
EOF
else
    echo "    (config already exists, leaving it alone)"
fi

echo "==> Installing launchd agent ($LABEL, every $((INTERVAL / 60)) min)"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$PYTHON|" \
    -e "s|__SCRIPT__|$PROJECT_DIR/notes_backup.py|" \
    -e "s|__INTERVAL__|$INTERVAL|" \
    -e "s|__LOG__|$LOG|" \
    "$PROJECT_DIR/$LABEL.plist.template" > "$PLIST"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

cat <<EOF

Installed. One manual step remains — grant Full Disk Access so the backup
can read the Apple Notes database:

  1. System Settings > Privacy & Security > Full Disk Access
  2. Click "+" and add this file (Cmd+Shift+G to paste the path):
       $PYTHON
  3. (Optional, for running backups by hand) also add your terminal app.

Then test with:
  launchctl kickstart "gui/\$UID/$LABEL" && sleep 5 && tail "$LOG"

Backups: $BACKUP_DIR   Log: $LOG
EOF

open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
