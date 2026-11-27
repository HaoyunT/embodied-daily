#!/usr/bin/env bash
# embodied-daily installer (macOS): installs the Claude Code skill and a launchd job.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DST="$HOME/Library/LaunchAgents/com.embodied.daily.plist"
SKILL_DST="$HOME/.claude/skills/embodied-daily"

echo "📂 Repo: $REPO"

# 1. Config file
if [ ! -f "$REPO/config.json" ]; then
  cp "$REPO/config.example.json" "$REPO/config.json"
  echo "📝 Created config.json — edit it to add your Bark key: $REPO/config.json"
fi
mkdir -p "$REPO/logs" "$REPO/archive"

# 2. Claude Code skill (with this repo's path filled in)
mkdir -p "$SKILL_DST"
sed -e "s#__REPO__#$REPO#g" "$REPO/skill/SKILL.md" > "$SKILL_DST/SKILL.md"
echo "🧩 Installed skill to $SKILL_DST"

# 3. launchd job (daily at 09:30 local time)
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" \
  "$REPO/launchd/com.embodied.daily.plist.template" > "$PLIST_DST"
plutil -lint "$PLIST_DST" >/dev/null

launchctl bootout "gui/$(id -u)/com.embodied.daily" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "⏰ Registered launchd job: runs daily at 09:30"

echo ""
echo "✅ Done!"
echo "   Test now:      python3 \"$REPO/embodied_daily.py\""
echo "   Today's digest: cat \"$REPO/archive/\$(date +%F).md\""
