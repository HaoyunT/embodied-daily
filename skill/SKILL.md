---
name: embodied-daily
description: Generate or view today's Embodied AI paper digest — fetches the latest embodied-AI papers from arXiv and gives a ranked Top-N with digests, arXiv links, code links and topic tags; pushes to iPhone (Bark) and shows a macOS notification. Use when the user asks for "embodied daily", "today's embodied AI papers", or the embodied paper digest.
---

# Embodied AI Daily (embodied-daily)

A launchd job runs `__REPO__/embodied_daily.py` every day at 09:30. It pushes the top papers to iPhone (one Bark notification per paper), shows a macOS summary notification, and archives the digest as Markdown. Use this skill to **trigger a run manually** or to **inspect / adjust** the setup.

## User intents and actions

### 1. Generate today's digest now (full pipeline)
```bash
python3 __REPO__/embodied_daily.py              # fetch → curate → push → archive
python3 __REPO__/embodied_daily.py --no-deliver # fetch → curate → archive only (no push)
```
Afterwards, read `__REPO__/latest.md` and show its content to the user.

### 2. View a past digest (no new fetch)
```bash
cat __REPO__/latest.md          # most recent run
ls __REPO__/archive/            # all archived days
cat __REPO__/archive/YYYY-MM-DD.md
```

### 3. One-off look in the conversation, without pushing
Fetch
`https://export.arxiv.org/api/query?search_query=cat:cs.RO+OR+all:embodied&sortBy=submittedDate&sortOrder=descending&max_results=30`
with WebFetch, then pick the top embodied-AI papers and give a digest, arXiv link, code link (a GitHub URL from the abstract, otherwise "N/A") and topic tag for each.

### 4. Change configuration
Edit `__REPO__/config.json`:
- `bark_key`: Bark device key for iPhone push (**required for push**)
- `interests`: research interests, highest priority first (e.g. "VLA, dexterous hands")
- `language`: digest language (default "English")
- `top_n` / `push_n`: papers in the digest / pushed to the phone (default 10 / 5)
- `queries`: arXiv search queries
- `use_claude_cli`: enable AI curation (default true)

See the repo README for the full list.

### 5. Troubleshoot the scheduled job
```bash
launchctl print gui/$(id -u)/com.embodied.daily | grep -E "state|last exit"
cat __REPO__/logs/stdout.log
cat __REPO__/logs/stderr.log
```
Reload:
```bash
launchctl bootout gui/$(id -u)/com.embodied.daily
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.embodied.daily.plist
```

## Notes
- Locally, curation uses the `claude` CLI (your Claude login), so no API key is needed. If neither `ANTHROPIC_API_KEY` nor the CLI is available, it falls back to raw abstracts + keyword tags.
- arXiv does not announce on weekends; on Saturday/Sunday the script sends a recap of this week's papers that were not pushed yet.
- launchd only runs while the Mac is awake; a missed run is executed after wake.
