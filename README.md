# 📚 embodied-daily · 每日具身智能论文日报

> 每天早上 9:30 自动从 arXiv 抓取最新的**具身智能 (Embodied AI)** 论文，用 AI 精选 Top10，
> 生成详细中文解读：**Mac 看全部 10 篇**（自动打开 Markdown 日报），**iPhone 推前 5 篇**（Bark 每篇一条），全文本地存档。
> 全程无人值守，不需要打开任何程序。

---

## ✨ 特性

- 🔍 **自动抓取**：从 arXiv 多路检索（`cs.RO`、embodied、VLA、robot manipulation 等）合并去重
- 🧠 **AI 精选解读**（PaperLocus 风格：文献定位 + 区分论文断言/推断）——云端用 **Anthropic API**，本机用 `claude` CLI（复用 Claude 订阅）：
  - Top10 重要性排序
  - 一句话亮点（TL;DR）+ 🧭 文献定位（built on A, changed B → C）
  - 详细中文解读（问题 / 方法 / 创新点 / 实验结果 / 价值）
  - 关键要点列表 + 方向标签
- 💻 **代码链接**：自动从摘要 / Papers with Code 抽取 GitHub 仓库，没有则如实标「暂无」
- 📲 **送达 iPhone + Mac**：精选 Top10 中**前 5 篇**每篇单独推送一条详细解读到 iPhone（Bark）；Mac 弹汇总通知并自动打开含**全部 10 篇**的日报 Markdown，全文同时本地存档
- ⏰ **定时无人值守**：☁️ GitHub Actions（关机也能跑，推荐）或本机 `launchd`，每天 9:30 自动运行
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

## ☁️ 云端运行（GitHub Actions，推荐：不依赖本机、Mac 关机也能收到）

本机 `launchd` 只在 Mac 开机且未睡眠时才会运行。要做到**每天 9:30 雷打不动、关机也照推**，用仓库内置的 GitHub Actions 工作流（`.github/workflows/daily.yml`，已配置北京时间 9:30）。

云端没有本机的 `claude` 登录态，因此用 **Anthropic API** 生成中文摘要（按量付费，每天约几分钱）。

**一次性配置（在你的 GitHub 仓库页面）：**

1. **Settings → Secrets and variables → Actions → New repository secret**，添加两个 Secret：
   - `ANTHROPIC_API_KEY`：你的 Anthropic API key（[console.anthropic.com](https://console.anthropic.com) 获取）
   - `BARK_KEY`：你的 Bark 推送 key
2. （可选）在同页 **Variables** 标签添加：
   - `EMBODIED_INTERESTS`：兴趣偏好，如 `VLA, 灵巧手`
   - `ANTHROPIC_MODEL`：模型，默认 `claude-sonnet-4-6`
3. **Actions** 页面找到「每日具身智能日报」工作流，点 **Run workflow** 手动跑一次验证。

之后每天 9:30（UTC 1:30）自动运行：抓取 → API 精选解读 → 推送 iPhone → 把当天日报存档提交回仓库。

> ⚠️ GitHub Actions 的定时触发可能延迟几分钟到几十分钟（平台特性），属正常现象。

## ⚙️ 配置项（`config.json`）

| 字段 | 说明 | 默认 |
|---|---|---|
| `bark_key` | Bark 推送 key（必填才会推 iPhone） | `""` |
| `bark_server` | Bark 服务器（自建可改） | `https://api.day.app` |
| `top_n` | 精选篇数：Mac 日报 / 存档展示全部 `top_n` 篇 | `10` |
| `push_n` | iPhone 只推送前 `push_n` 篇（≤ `top_n`） | `5` |
| `interests` | **个人兴趣偏好**：填你关注的方向，相关论文会被优先选入并排前面（留空则不偏向） | `""` |
| `same_day_only` | **只推当日**：仅保留最新一个公布日的论文，不跨多天（即使不足 `top_n` 也不向前补） | `true` |
| `lookback_days` | `same_day_only=false` 时生效：回看最近几天 | `3` |
| `max_candidates` | 送 AI 精选的候选上限（即"分母"） | `40` |
| `queries` | arXiv 检索式数组 | 见文件 |
| `use_claude_cli` | 是否启用 AI 摘要（云端走 Anthropic API，本机走 `claude` CLI） | `true` |
| `api_model` | 云端 Anthropic API 用的模型（环境变量 `ANTHROPIC_MODEL` 可覆盖） | `claude-sonnet-4-6` |
| `claude_bin` | claude 可执行文件路径（留空自动探测） | `""` |
| `open_digest` | 跑完后是否自动用默认程序打开当天日报 `latest.md`（Mac） | `true` |

> 💡 **个人化例子**：把 `interests` 设成 `"VLA, 灵巧手操作, 世界模型"`，每天的 Top10 就会更偏向这些方向。

## 🔢 Top10 是怎么选出来 & 排序的（iPhone 取前 5）

分两步：

**第一步 · 圈定候选池（"分母"，纯按时间）**
从多路 arXiv 检索（`cs.RO` / embodied / VLA / robot manipulation）抓取结果，合并去重。默认 `same_day_only=true`，**只保留最新一个公布日的论文**（不跨多天），按提交时间倒序，取前 `max_candidates`（默认 **40**）篇作为候选。
→ 所以分母 = **当日那一批**具身论文（运行日志里 `当日批次: 日期 篇数: N` 就是它）。若关掉 `same_day_only`，则改为回看 `lookback_days` 天。

**第二步 · AI 精选 + 排序（按"重要性 + 相关性"）**
把这批候选的**标题 + 摘要**整体发给 `claude`，让它：
1. 挑出与具身智能最相关、最有价值的 `top_n`（默认 **10**）篇；
2. **按重要性从高到低排序**；
3. 若配置了 `interests`，则**与你兴趣相关的优先选入、排更靠前**。

最终：**Mac 日报 / 存档展示全部 `top_n`（10）篇**，**iPhone 只推送排在最前的 `push_n`（5）篇**。

> ⚠️ **说明**：排序是 `claude` 基于摘要内容的**主观判断**，不依据引用量、作者或机构等硬指标，因此带有模型主观性，同一天重跑顺序可能略有变化。想要更可控，可在 `config.json` 里用 `interests` 引导，或自行修改脚本中 `claude_curate()` 的 prompt。

## 🧱 工作原理

```
arXiv API ──▶ 合并去重/按日期筛选 ──▶ claude CLI 精选Top10+中文解读
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
