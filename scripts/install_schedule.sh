#!/bin/bash
# Usage: scripts/install_schedule.sh /path/to/ARTREND_magazine_data
# Installs the daily job (starts 07:00, publishes 08:30) for the current user (launchd). Remove with:
#   launchctl unload ~/Library/LaunchAgents/com.artrend.daily.plist && rm ~/Library/LaunchAgents/com.artrend.daily.plist
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PIPE="${1:?pipeline directory (holds db/, .env, .venv) required}"
DEST="$HOME/Library/LaunchAgents/com.artrend.daily.plist"
sed -e "s#__REPO__#$REPO#g" -e "s#__PIPELINE__#$PIPE#g" "$REPO/scripts/com.artrend.daily.plist" > "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "installed: $DEST (starts 07:00, publishes 08:30 KST) — run now with: launchctl start com.artrend.daily"
