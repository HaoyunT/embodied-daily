# 📚 embodied-daily · 每日具身智能论文日报

> 每天早上 9:30 自动从 arXiv 抓取最新的**具身智能 (Embodied AI)** 论文，用 AI 精选 Top 5，
> 生成详细中文解读，Top5 每篇**单独推送一条到 iPhone**（Bark）+ **Mac 桌面汇总通知** + 本地 Markdown 存档。
> 全程无人值守，不需要打开任何程序。

---

## ✨ 特性

- 🔍 **自动抓取**：从 arXiv 多路检索（`cs.RO`、embodied、VLA、robot manipulation 等）合并去重
- 🧠 **AI 精选解读**：调用本机 `claude` CLI（复用你的 Claude 订阅，**无需单独 API key**）做：
  - Top 5 重要性排序
  - 一句话亮点（TL;DR）
  - 详细中文摘要（问题 / 方法 / 创新点 / 结果 / 价值）
  - 关键要点列表 + 方向标签
- 💻 **代码链接**：自动从摘要 / Papers with Code 抽取 GitHub 仓库，没有则如实标「暂无」
- 📲 **送达 iPhone + Mac**：Top5 每篇单独推送一条详细解读（Bark）；Mac 弹一条汇总通知，并自动打开含全部 5 篇的日报 Markdown，全文同时本地存档
- ⏰ **定时无人值守**：macOS `launchd` 每天 9:30 自动运行，**不依赖终端是否打开**
- 🛟 **优雅降级**：`claude` CLI 不可用时自动退化为英文摘要 + 关键词标签

## 🚀 安装

```bash
git clone <你的仓库地址> embodied-daily
cd embodied-daily
cp config.example.json config.json   # 然后填入你的 Bark key
bash install.sh                        # 安装 skill + 注册 launchd 定时任务
```

### 配置 Bark（iPhone 推送）

1. iPhone App Store 安装免费 App **Bark**
2. 打开后复制你的推送 key（URL 中 `https://api.day.app/`**`XXXXXX`** 那段）
3. 填入 `config.json` 的 `bark_key`

### 手动运行 / 测试

```bash
python3 embodied_daily.py            # 立即抓取+解读+推送+存档
cat archive/$(date +%F).md           # 查看今天的日报
```

在 Claude Code 里也可以直接 `/embodied-daily` 手动触发或排查。

## ⚙️ 配置项（`config.json`）

| 字段 | 说明 | 默认 |
|---|---|---|
| `bark_key` | Bark 推送 key（必填才会推 iPhone） | `""` |
| `bark_server` | Bark 服务器（自建可改） | `https://api.day.app` |
| `top_n` | 每天精选篇数（最终推送几篇） | `5` |
| `interests` | **个人兴趣偏好**：填你关注的方向，相关论文会被优先选入并排前面（留空则不偏向） | `""` |
| `lookback_days` | 回看天数（arXiv 周末不更新，兜底） | `3` |
| `max_candidates` | 送 AI 精选的候选上限（即"分母"） | `40` |
| `queries` | arXiv 检索式数组 | 见文件 |
| `use_claude_cli` | 是否用 `claude` CLI 做中文摘要 | `true` |
| `claude_bin` | claude 可执行文件路径（留空自动探测） | `""` |
| `open_digest` | 跑完后是否自动用默认程序打开当天日报 `latest.md`（Mac） | `true` |

> 💡 **个人化例子**：把 `interests` 设成 `"VLA, 灵巧手操作, 世界模型"`，每天的 Top5 就会更偏向这些方向。

## 🔢 Top5 是怎么选出来 & 排序的

分两步：

**第一步 · 圈定候选池（"分母"，纯按时间）**
从多路 arXiv 检索（`cs.RO` / embodied / VLA / robot manipulation）抓取结果，合并去重，只保留最近 `lookback_days`（默认 3）天的论文，按提交时间倒序，取前 `max_candidates`（默认 **40**）篇作为候选。
→ 所以**分母默认最多 40 篇**（实际数量随当天 arXiv 更新量浮动，运行日志里的 `候选数: N` 就是它）。

**第二步 · AI 精选 + 排序（按"重要性 + 相关性"）**
把这批候选的**标题 + 摘要**整体发给 `claude`，让它：
1. 挑出与具身智能最相关、最有价值的 `top_n`（默认 5）篇；
2. **按重要性从高到低排序**；
3. 若配置了 `interests`，则**与你兴趣相关的优先选入、排更靠前**。

> ⚠️ **说明**：排序是 `claude` 基于摘要内容的**主观判断**，不依据引用量、作者或机构等硬指标，因此带有模型主观性，同一天重跑顺序可能略有变化。想要更可控，可在 `config.json` 里用 `interests` 引导，或自行修改脚本中 `claude_curate()` 的 prompt。

## 🧱 工作原理

```
arXiv API ──▶ 合并去重/按日期筛选 ──▶ claude CLI 精选Top5+中文解读
                                            │
              ┌─────────────────────────────┼──────────────────────┐
              ▼                             ▼                       ▼
   Bark → iPhone(每篇一条详细)        Mac 桌面汇总通知          Markdown 存档
```

## 📁 目录结构

```
embodied-daily/
├── embodied_daily.py          # 主脚本（仅依赖 Python 标准库 + 系统 curl）
├── config.example.json        # 配置模板
├── config.json                # 你的配置（含 Bark key，已 gitignore）
├── install.sh                 # 一键安装：装 skill + 注册 launchd
├── skill/SKILL.md             # Claude Code skill 源文件
├── launchd/                   # launchd 定时任务模板
├── archive/                   # 每日日报存档（Markdown）
└── logs/                      # 运行日志（已 gitignore）
```

## 📋 依赖

- macOS（用到 `launchd` 定时与 `osascript` 桌面通知）
- Python 3（系统自带 `/usr/bin/python3` 即可）
- 系统 `curl`
- 可选：[`claude` CLI](https://claude.com/claude-code)（用于高质量中文摘要）

## 📝 License

MIT
