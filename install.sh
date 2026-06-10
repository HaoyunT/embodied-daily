#!/usr/bin/env bash
# embodied-daily 一键安装：注册 launchd 定时任务 + 安装 Claude Code skill
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
PLIST_DST="$HOME_DIR/Library/LaunchAgents/com.embodied.daily.plist"
SKILL_DST="$HOME_DIR/.claude/skills/embodied-daily"

echo "📂 仓库目录: $REPO"

# 1. 配置文件
if [ ! -f "$REPO/config.json" ]; then
  cp "$REPO/config.example.json" "$REPO/config.json"
  echo "📝 已生成 config.json，请填入你的 Bark key（编辑 $REPO/config.json）"
fi
mkdir -p "$REPO/logs" "$REPO/archive"

# 2. 安装 Claude Code skill
mkdir -p "$SKILL_DST"
cp "$REPO/skill/SKILL.md" "$SKILL_DST/SKILL.md"
echo "🧩 已安装 skill 到 $SKILL_DST"

# 3. 生成并注册 launchd 定时任务（每天 9:30）
mkdir -p "$HOME_DIR/Library/LaunchAgents"
sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME_DIR#g" \
  "$REPO/launchd/com.embodied.daily.plist.template" > "$PLIST_DST"
plutil -lint "$PLIST_DST" >/dev/null

launchctl bootout "gui/$(id -u)/com.embodied.daily" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "⏰ 已注册定时任务，每天 09:30 自动运行"

echo ""
echo "✅ 安装完成！"
echo "   立即测试：python3 \"$REPO/embodied_daily.py\""
echo "   查看今天：cat \"$REPO/archive/\$(date +%F).md\""
