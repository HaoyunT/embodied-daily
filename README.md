# 📚 embodied-daily - Daily Embodied AI Paper Digest

> Every morning at 9:30, automatically pull the latest **Embodied AI** papers from arXiv and use AI to pick the Top 5,
> Generate detailed Chinese analyses; each Top5 paper is **pushed separately to iPhone** (Bark) + **one Mac desktop summary notification** + local Markdown archive.
> Fully unattended, no need to open any app.

---

## ✨ Features

- 🔍 **Auto-fetch**: multi-query search on arXiv (`cs.RO`, embodied, VLA, robot manipulation, etc.), merged and deduplicated
- 🧠 **AI selection + commentary**: uses the local `claude` CLI (reuses your Claude subscription, **no separate API key needed**) to:
  - Top 5 ranked by importance
  - One-line highlight (TL;DR)
  - Detailed Chinese summary (problem / method / novelty / results / value)
  - Key points list + direction tags
- 💻 **Code links**: auto-extract the GitHub repo from the abstract or Papers with Code, otherwise honestly mark 'none'
- 📲 **Delivered to iPhone + Mac**: each of the Top 5 gets its own detailed post (Bark), Mac shows one summary notification, and a local Markdown archive is kept
- ⏰ **Scheduled and unattended**: macOS `launchd` runs it automatically at 9:30 daily, **no need for the terminal to be open**
- 🛟 **Graceful degradation**: falls back to English abstracts + keyword tags when the `claude` CLI is unavailable

## 🚀 Install

```bash
git clone <your-repo-url> embodied-daily
cd embodied-daily
cp config.example.json config.json   # then fill in your Bark key
bash install.sh                        # install the skill + register the launchd job
```

### Configure Bark (iPhone push)

1. Install the free **Bark** app from the iPhone App Store
2. Open it and copy your push key (the **`XXXXXX`** part of the URL `https://api.day.app/`)
3. Put it in `bark_key` in `config.json`

### Manual run / test

```bash
python3 embodied_daily.py            # fetch + review + push + archive right away
cat archive/$(date +%F).md           # view today's digest
```

In Claude Code you can also type `/embodied-daily` to trigger it or debug by hand.

## ⚙️ Configuration options (`config.json`)

| Field | Description | Default |
|---|---|---|
| `bark_key` | Bark push key (required for iPhone push) | `""` |
| `bark_server` | Bark server (change if self-hosted) | `https://api.day.app` |
| `top_n` | Number of papers selected per day (how many get pushed in the end) | `5` |
| `interests` | **Personal interest preferences**: list the directions you care about; related papers are prioritized and ranked first (leave empty for no bias) | `""` |
| `lookback_days` | Days to look back (arXiv does not update on weekends, so this is a fallback) | `3` |
| `max_candidates` | Max number of candidates sent to AI for curation (i.e. the "denominator") | `40` |
| `queries` | Array of arXiv search queries | See file |
| `use_claude_cli` | whether to use the `claude` CLI for Chinese summaries | `true` |
| `claude_bin` | Path to the claude executable (auto-detected if empty) | `""` |

> 💡 **Personalization example**: set `interests` to `"VLA, dexterous hand manipulation, world models"` and the daily Top5 will lean toward these directions.

## 🔢 How Top5 is selected & ranked

Two steps:

**Step 1 · Define the candidate pool (the "denominator", by time only)**
Fetch results from multiple arXiv queries (`cs.RO` / embodied / VLA / robot manipulation), merge and dedupe, keep only papers from the last `lookback_days` (default 3) days, sort by submission time descending, and take the first `max_candidates` (default **40**) as candidates.
→ So the **denominator defaults to at most 40 papers** (the actual count varies with how much arXiv updates that day; `candidates: N` in the run log is exactly it).

**Step 2 · AI curation + ranking (by "importance + relevance")**
Send this batch of candidates' **titles + abstracts** to `claude` in one go, and have it:
1. Pick the `top_n` (default 5) most relevant and valuable Embodied AI papers;
2. **Sort by importance, high to low**;
3. If `interests` is configured, **papers relevant to your interests are picked first and ranked higher**.

> ⚠️ **Note**: the ranking is a **subjective judgment** by `claude` based on the abstracts, not on hard metrics such as citation count, authors, or institutions. It therefore carries model subjectivity, and rerunning on the same day may slightly change the order. For more control, steer it with `interests` in `config.json`, or edit the prompt of `claude_curate()` in the script yourself.

## 🧱 How it works

```
arXiv API ──▶ merge, dedupe / filter by date ──▶ claude CLI selects Top 5 + Chinese commentary
                                            │
              ┌─────────────────────────────┼──────────────────────┐
              ▼                             ▼                       ▼
   Bark → iPhone(one detailed item per paper)        Mac desktop summary notification          Markdown archive
```

## 📁 Directory structure

```
embodied-daily/
├── embodied_daily.py          # main script (only needs the Python stdlib + system curl)
├── config.example.json        # config template
├── config.json                # your config (includes Bark key, already gitignored)
├── install.sh                 # One-click install: installs skill + registers launchd
├── skill/SKILL.md             # Claude Code skill source file
├── launchd/                   # launchd scheduled task templates
├── archive/                   # daily digest archive (Markdown)
└── logs/                      # run logs (gitignored)
```

## 📋 Dependencies

- macOS (uses `launchd` for scheduling and `osascript` for desktop notifications)
- Python 3 (the built-in `/usr/bin/python3` is enough)
- System `curl`
- Optional: [`claude` CLI](https://claude.com/claude-code) (for high-quality Chinese summaries)

## 📝 License

MIT
