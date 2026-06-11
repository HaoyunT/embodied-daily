# 📚 embodied-daily - Daily Embodied AI Paper Digest

> Every morning at 9:30, automatically pull the latest **Embodied AI** papers from arXiv, pick the Top 10 with AI,
> and write detailed Chinese reviews: **Mac shows all 10** (opens the Markdown digest automatically), **iPhone gets the top 5** (one Bark push each), everything archived locally.
> Fully unattended, no need to open any app.

---

## ✨ Features

- 🔍 **Auto-fetch**: multi-query search on arXiv (`cs.RO`, embodied, VLA, robot manipulation, etc.), merged and deduplicated
- 🧠 **AI-picked reviews** (PaperLocus style: literature positioning + separating paper claims from inference), using the **Anthropic API** in the cloud and the `claude` CLI locally (reuses your Claude subscription):
  - Top 10 ranked by importance
  - One-line highlight (TL;DR) + 🧭 literature positioning (built on A, changed B -> C)
  - Detailed Chinese review (problem / method / novelty / results / value)
  - Key points list + direction tags
- 💻 **Code links**: auto-extract the GitHub repo from the abstract or Papers with Code, otherwise honestly mark 'none'
- 📲 **Delivery to iPhone + Mac**: each of the **top 5** of the Top 10 gets its own detailed push to iPhone (Bark); Mac gets a summary notification and auto-opens the daily Markdown with **all 10** papers, full text archived locally too
- ⏰ **Scheduled and unattended**: ☁️ GitHub Actions (runs even when the machine is off, recommended) or local `launchd`, runs daily at 9:30
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

## ☁️ Cloud run (GitHub Actions, recommended: no local machine needed, works even when the Mac is off)

Local `launchd` only runs when the Mac is awake and not asleep. For **a reliable daily run at 9:30 that pushes even when the machine is off**, use the bundled GitHub Actions workflow (`.github/workflows/daily.yml`, already set to 9:30 Beijing time).

The cloud has no local `claude` login, so it uses the **Anthropic API** to generate the Chinese summaries (pay per use, a few cents a day).

**One-time setup (on your GitHub repository page):**

1. **Settings → Secrets and variables → Actions → New repository secret**, add two Secrets:
   - `ANTHROPIC_API_KEY`: Anthropic API key (official [console.anthropic.com](https://console.anthropic.com), or a key from a third-party relay service; the latter requires setting `ANTHROPIC_BASE_URL` under Variables)
   - `BARK_KEY`: your Bark push key
2. (Optional) On the same page, under the **Variables** tab, add:
   - `ANTHROPIC_BASE_URL`: **required if using a third-party relay API**, set it to the relay service address (e.g. `https://xxx.example.com`; not needed for the official API)
   - `EMBODIED_INTERESTS`: interest preferences, e.g. `VLA, dexterous hands`
   - `ANTHROPIC_MODEL`: model, defaults to `claude-sonnet-4-6`
3. On the **Actions** page, find the 'Daily Embodied AI Digest' workflow and click **Run workflow** to run it manually once to verify.

After that it runs automatically every day at 9:30 (UTC 1:30): fetch → API curation and summaries → push to iPhone → commit the archived digest of the day back to the repository.

> ⚠️ Scheduled triggers on GitHub Actions may be delayed by a few minutes to tens of minutes (a platform characteristic); this is normal.

## ⚙️ Configuration options (`config.json`)

| Field | Description | Default |
|---|---|---|
| `bark_key` | Bark push key (required for iPhone push) | `""` |
| `bark_server` | Bark server (change if self-hosted) | `https://api.day.app` |
| `top_n` | Number of curated papers: the Mac digest / archive shows all `top_n` papers | `10` |
| `push_n` | iPhone only receives the first `push_n` papers (≤ `top_n`) | `5` |
| `interests` | **Personal interest preferences**: list the directions you care about; related papers are prioritized and ranked first (leave empty for no bias) | `""` |
| `same_day_only` | **Same day only**: keep only papers from the most recent announcement date, never spanning multiple days (no backfilling from earlier days even if fewer than `top_n`) | `true` |
| `lookback_days` | Takes effect when `same_day_only=false`: how many recent days to look back | `3` |
| `max_candidates` | Max number of candidates sent to AI for curation (i.e. the "denominator") | `40` |
| `queries` | Array of arXiv search queries | See file |
| `use_claude_cli` | Whether to enable AI summaries (cloud uses the Anthropic API, local uses the `claude` CLI) | `true` |
| `api_model` | Model used by the cloud Anthropic API (can be overridden by the `ANTHROPIC_MODEL` environment variable) | `claude-sonnet-4-6` |
| `api_base_url` | API address (set to the relay address for third-party relays; can be overridden by the `ANTHROPIC_BASE_URL` environment variable) | `https://api.anthropic.com` |
| `claude_bin` | Path to the claude executable (auto-detected if empty) | `""` |
| `open_digest` | Whether to automatically open the daily digest `latest.md` with the default app after running (Mac) | `true` |

> 💡 **Personalization example**: set `interests` to `"VLA, dexterous hand manipulation, world models"` and the daily Top10 will lean toward these directions.

## 🔢 How the Top10 is selected & ranked (iPhone gets the first 5)

Two steps:

**Step 1 · Define the candidate pool (the "denominator", by time only)**
Fetch results from multiple arXiv searches (`cs.RO` / embodied / VLA / robot manipulation), merge and dedupe. Default `same_day_only=true`, **keep only papers from the latest announcement day** (no multi-day span), sort by submission time descending, and take the first `max_candidates` (default **40**) as candidates.
→ So the denominator = the **same-day batch** of embodied papers (that is the `same-day batch: <date> count: N` line in the run log). If `same_day_only` is off, it falls back to looking back `lookback_days` days.

**Step 2 · AI curation + ranking (by "importance + relevance")**
Send this batch of candidates' **titles + abstracts** to `claude` in one go, and have it:
1. Pick the `top_n` (default **10**) papers most relevant and valuable to Embodied AI;
2. **Sort by importance, high to low**;
3. If `interests` is configured, **papers relevant to your interests are picked first and ranked higher**.

Final: **the Mac digest / archive shows all `top_n` (10) papers**, while **iPhone only pushes the top `push_n` (5)**.

> ⚠️ **Note**: the ranking is a **subjective judgment** by `claude` based on the abstracts, not on hard metrics such as citation count, authors, or institutions. It therefore carries model subjectivity, and rerunning on the same day may slightly change the order. For more control, steer it with `interests` in `config.json`, or edit the prompt of `claude_curate()` in the script yourself.

## 🧱 How it works

```
arXiv API ──▶ merge/dedupe/filter by date ──▶ claude CLI curates Top10 + Chinese commentary
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
