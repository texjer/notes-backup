#!/bin/zsh
# Removes the launchd agent and config. Never touches your backups.
set -euo pipefail

LABEL="local.notes-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed launchd agent."

echo "Left in place (delete yourself if you want them gone):"
echo "  - Your backups (see backup_dir in ~/.config/notes-backup/config.json)"
echo "  - ~/.config/notes-backup/"
echo "  - The Full Disk Access grant in System Settings"
