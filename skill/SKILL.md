---
name: embodied-daily
description: Generate/view today's Embodied AI paper digest -- fetch the latest embodied-AI papers from arXiv, with Chinese summaries, arXiv links, code repositories, and direction tags, Top5. Can be run manually; each paper's detailed analysis is pushed separately to iPhone (Bark), plus a summary notification on Mac. Use when the user says "daily embodied digest", "today's embodied papers", or "embodied daily".
---

# Embodied AI Daily Digest (embodied-daily)

At 9:30 every day launchd automatically runs `~/embodied-daily/embodied_daily.py`, **pushing a separate detailed write-up for each of the Top5 papers to the iPhone (Bark)**, showing **one summary notification on the Mac**, and archiving it as Markdown. This skill is for **manual triggering** or **viewing and adjusting**.

## User intents and matching actions

### 1. Generate today's digest now (manually trigger the whole pipeline)
Run the script; it fetches from arXiv → claude Chinese summaries → one Bark push per paper + one Mac summary notification → archive:
```bash
/usr/bin/python3 ~/embodied-daily/embodied_daily.py
```
After it finishes, read `~/embodied-daily/latest.md` and also show its content to the user in the conversation.

### 2. View the latest digest or one from a specific day (without re-fetching)
```bash
cat ~/embodied-daily/latest.md            # most recent
ls ~/embodied-daily/archive/              # all archives
cat ~/embodied-daily/archive/2026-06-10.md
```
After reading, format the content and show it to the user.

### 3. View in the session only, no push
Use the fetch logic in the script for a one-off survey: use WebFetch to pull
`https://export.arxiv.org/api/query?search_query=cat:cs.RO+OR+all:embodied&sortBy=submittedDate&sortOrder=descending&max_results=30`
Then pick the Top 5 embodied-AI papers and give a Chinese summary + arXiv link + code link (search the summary for github, mark "none" if absent) + topic tag.

### 4. Adjust configuration
Edit `~/embodied-daily/config.json`:
- `bark_key`: iPhone Bark push key (**required on first use**)
- `interests`: personal interest preferences (e.g. "VLA, dexterous hands"); matching papers are picked first and ranked higher
- `top_n`: number of papers per day (default 5)
- `lookback_days`: how many recent days to fetch (default 3)
- `queries`: array of arXiv search queries
- `use_claude_cli`: whether to use the local claude CLI to generate Chinese summaries (default true)

### 5. Troubleshoot the scheduled task
```bash
launchctl print gui/$(id -u)/com.embodied.daily | grep -E "state|last exit"
cat ~/embodied-daily/logs/stdout.log
cat ~/embodied-daily/logs/stderr.log
```
Reload:
```bash
launchctl bootout gui/$(id -u)/com.embodied.daily
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.embodied.daily.plist
```

## Notes
- Chinese summaries reuse the local `claude` CLI (your Claude subscription), so no separate API key is needed; if the CLI is unavailable it falls back to an English summary + keyword tags.
- arXiv may not update on weekends/holidays, so `lookback_days` defaults to a 3-day lookback as a fallback.
- launchd jobs only take effect when the Mac is on; if the lid is closed and it sleeps, missed tasks for that day run after wake.
