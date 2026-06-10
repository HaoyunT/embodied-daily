---
name: embodied-daily
description: 生成/查看今日具身智能(Embodied AI)论文日报 —— 从 arXiv 抓取最新具身相关论文, 给出中文摘要、arXiv链接、代码仓库、方向标签, Top5。可手动触发, 每篇单独推送一条详细解读到 iPhone(Bark), 并在 Mac 弹一条汇总通知。当用户说"具身日报""今天的具身论文""embodied daily"时使用。
---

# 具身智能日报 (embodied-daily)

每天 9:30 由 launchd 自动运行 `~/embodied-daily/embodied_daily.py`，把 Top5 论文**每篇单独推送一条详细解读到 iPhone(Bark)**、在 **Mac 弹一条汇总通知**，并存档为 Markdown。本 skill 用于**手动触发**或**查看/调整**。

## 用户意图与对应动作

### 1. 立即生成今天的日报（手动触发整条链路）
运行脚本，它会抓取 arXiv → claude 中文摘要 → 每篇一条推送到 Bark + Mac 汇总通知 → 存档：
```bash
/usr/bin/python3 ~/embodied-daily/embodied_daily.py
```
跑完后读取 `~/embodied-daily/latest.md` 并在会话里把内容也展示给用户。

### 2. 查看最近一次/某天的日报（不重新抓取）
```bash
cat ~/embodied-daily/latest.md            # 最近一次
ls ~/embodied-daily/archive/              # 所有存档
cat ~/embodied-daily/archive/2026-06-10.md
```
读取后把内容整理展示给用户。

### 3. 只在会话里看、不想推送
直接用脚本里的抓取逻辑做一次性调研：用 WebFetch 拉
`https://export.arxiv.org/api/query?search_query=cat:cs.RO+OR+all:embodied&sortBy=submittedDate&sortOrder=descending&max_results=30`
然后挑 Top5 具身相关论文，给中文摘要 + arXiv 链接 + 代码链接（在摘要里找 github，没有就标"暂无"）+ 方向标签。

### 4. 调整配置
编辑 `~/embodied-daily/config.json`：
- `bark_key`: iPhone Bark 推送 key（**首次使用必须填**）
- `interests`: 个人兴趣偏好（如 "VLA, 灵巧手"），相关论文会被优先选入并排前面
- `top_n`: 每天篇数（默认 5）
- `lookback_days`: 抓取最近几天（默认 3）
- `queries`: arXiv 检索式数组
- `use_claude_cli`: 是否用本机 claude CLI 生成中文摘要（默认 true）

### 5. 排查定时任务
```bash
launchctl print gui/$(id -u)/com.embodied.daily | grep -E "state|last exit"
cat ~/embodied-daily/logs/stdout.log
cat ~/embodied-daily/logs/stderr.log
```
重新加载：
```bash
launchctl bootout gui/$(id -u)/com.embodied.daily
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.embodied.daily.plist
```

## 注意
- 中文摘要复用本机 `claude` CLI（你的 Claude 订阅），无需单独 API key；若 CLI 不可用会退化为英文摘要 + 关键词标签。
- arXiv 周末/节假日可能不更新，`lookback_days` 默认回看 3 天兜底。
- launchd 任务只在 Mac 开机时生效；合盖睡眠时会在唤醒后补跑当天遗漏的任务。
