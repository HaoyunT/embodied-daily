#!/usr/bin/env bash
# embodied-daily one-click install: register a launchd scheduled task + install the Claude Code skill
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
PLIST_DST="$HOME_DIR/Library/LaunchAgents/com.embodied.daily.plist"
SKILL_DST="$HOME_DIR/.claude/skills/embodied-daily"

echo "📂 Repo directory: $REPO"

# 1. Config file
if [ ! -f "$REPO/config.json" ]; then
  cp "$REPO/config.example.json" "$REPO/config.json"
  echo "📝 config.json generated, please fill in your Bark key (edit $REPO/config.json)"
fi
mkdir -p "$REPO/logs" "$REPO/archive"

# 2. Install the Claude Code skill
mkdir -p "$SKILL_DST"
cp "$REPO/skill/SKILL.md" "$SKILL_DST/SKILL.md"
echo "🧩 Installed skill to $SKILL_DST"

# 3. Generate and register the launchd scheduled task (daily at 9:30)
mkdir -p "$HOME_DIR/Library/LaunchAgents"
sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME_DIR#g" \
  "$REPO/launchd/com.embodied.daily.plist.template" > "$PLIST_DST"
plutil -lint "$PLIST_DST" >/dev/null

launchctl bootout "gui/$(id -u)/com.embodied.daily" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "⏰ Scheduled task registered, runs daily at 09:30"

echo ""
echo "✅ Installation complete!"
echo "   Test now: python3 \"$REPO/embodied_daily.py\""
echo "   View today: cat \"$REPO/archive/\$(date +%F).md\""
