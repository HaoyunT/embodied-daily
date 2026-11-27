<div align="center">

# 📚 embodied-daily

### Your daily, AI-curated digest of new Embodied AI papers from arXiv

[![CI](https://img.shields.io/github/actions/workflow/status/HaoyunT/embodied-daily/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/HaoyunT/embodied-daily/actions/workflows/ci.yml)
[![Daily digest](https://img.shields.io/github/actions/workflow/status/HaoyunT/embodied-daily/daily.yml?branch=main&label=daily%20digest&style=flat-square)](https://github.com/HaoyunT/embodied-daily/actions/workflows/daily.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-stdlib%20only-2ea44f?style=flat-square)](#-requirements)
[![Claude](https://img.shields.io/badge/curated%20by-Claude-D97757?style=flat-square)](https://www.anthropic.com/claude)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/HaoyunT/embodied-daily?style=flat-square)](https://github.com/HaoyunT/embodied-daily/stargazers)

**arXiv → Claude picks & explains the Top 10 → iPhone push · Mac digest · email · Markdown archive**

[Example output](#-example-output) · [Quick start](#-quick-start) · [Run in the cloud](#%EF%B8%8F-run-in-the-cloud-github-actions) · [Configuration](#%EF%B8%8F-configuration) · [Archive](archive/)

</div>

---

Every morning at 09:30, embodied-daily pulls the newest **Embodied AI** papers from arXiv (VLA, robot manipulation, dexterous hands, humanoids, navigation, world models, sim-to-real, …). It asks Claude to pick the most important ones and writes a structured digest for each paper that places it in the context of prior work. The digest is delivered to your phone and desktop, and kept as a searchable Markdown archive. It runs unattended — on GitHub Actions (works even when your laptop is off) or locally via `launchd`.

## ✨ Features

| | |
|---|---|
| 🔍 **Multi-query fetching** | Merges and de-duplicates several arXiv queries (`cs.RO`, `embodied`, `vision-language-action`, `robot manipulation`, or your own). Only the newest announcement day is kept, and papers already covered in the last 7 days are skipped. |
| 🧠 **AI curation** | Claude ranks the candidates by importance (biased towards your `interests`) and writes for each paper a **TL;DR**, a **🧭 literature position** ("builds on A, changes B → C"), a **detailed digest** (problem / method / novelty / results / limits), and **highlights**. Inferences are marked as such; nothing is invented beyond the abstract. |
| 💻 **Code links** | Extracted from the abstract, with a Papers with Code fallback; shown as `N/A` when none exists. |
| 📲 **Delivery** | One [Bark](https://github.com/Finb/Bark) push per paper (top 5) to iPhone; a macOS notification plus the full Top 10 digest opened on your Mac; optional email with an HTML attachment. |
| 🗓️ **Weekend recap** | arXiv is quiet on weekends, so on Saturday and Sunday you get this week's papers that you haven't been sent yet. |
| 🌐 **Any language** | Digests are written in English by default; set `language` to e.g. `Chinese` to get them in another language. |
| 🛟 **Graceful fallback** | No API key and no `claude` CLI? You still get the Top N with raw abstracts and keyword tags. |
| 🪶 **Zero dependencies** | A single Python file using only the standard library (+ system `curl`). |

## 👀 Example output

Each day produces [`archive/YYYY-MM-DD.md`](archive/). An entry looks like this:

> ## 1. [VLA] Cairn: Object-Centric 3D Trajectory Priors for Steering Frozen VLAs
>
> > 💡 Steers a frozen VLA with object-centric 3D trajectory priors so it copes with moved objects and obstacles without layout-specific fine-tuning.
>
> **🧭 Position**: Builds on pretrained vision-language-action controllers whose object destinations are tied to training layouts, and replaces per-layout fine-tuning, which needs fresh robot data and erodes existing skills, with inference-time steering from object-centric 3D trajectory priors while the VLA stays frozen.
>
> The problem is that VLAs act as capable low-level controllers yet bind where objects go to the layouts seen in training, so when objects are moved or obstacles block the path they carry objects to the wrong place or into collisions. Fine-tuning on each new layout is costly because it requires robot data per layout and causes the model to lose skills it already had. Cairn keeps the VLA weights frozen and steers its behavior using object-centric 3D trajectory priors … The value lies in training-free adaptation to rearranged scenes and new obstacles while preserving pretrained skills. Limitations likely include dependence on the quality of the 3D trajectory priors and on 3D perception.
>
> **Highlights**:
> - VLA weights stay frozen; no per-layout robot data or fine-tuning
> - Object-centric 3D trajectory priors redirect destinations and avoid obstacles
> - Addresses skill erosion caused by fine-tuning on new layouts
>
> **Links**: 📄 [arXiv](https://arxiv.org/abs/2611.34914) · 📕 [PDF](https://arxiv.org/pdf/2611.34914v1) · 💻 Code: N/A

On your phone, each of the top 5 papers arrives as its own Bark notification with the same TL;DR, digest, highlights and links.

Archives generated before this repository switched to English are in Chinese and are kept as-is.

## 🔢 How papers are selected

1. **Candidate pool (by date).** All queries are merged and de-duplicated. With `same_day_only` (default), only papers from the newest arXiv announcement day are kept; papers already archived in the last `dedup_days` days are dropped. The newest `max_candidates` (40) form the pool.
2. **AI ranking (by importance + relevance).** Titles and abstracts are sent to Claude, which selects the `top_n` (10) most relevant and valuable papers, ranks them, and favours your `interests`.
3. **Delivery.** The Mac digest and archive show all `top_n` papers; the phone receives the first `push_n` (5), with `push_priority` matches moved to the front.

> [!NOTE]
> Ranking is the model's judgement based on abstracts only, not on citations, authors or venues, so re-running the same day can change the order slightly. Steer it with `interests`, or edit the prompt in `build_curate_prompt()`.

## 🚀 Quick start

```bash
git clone https://github.com/HaoyunT/embodied-daily.git
cd embodied-daily
cp config.example.json config.json       # then fill in bark_key, interests, ...
python3 embodied_daily.py --no-deliver   # fetch + curate + archive, no notifications
cat latest.md
```

Curation uses `ANTHROPIC_API_KEY` if it is set, otherwise the local [`claude` CLI](https://claude.com/claude-code) (your Claude login, no API key needed).

| Command | What it does |
|---|---|
| `python3 embodied_daily.py` | Full run: fetch → curate → archive → push / notify / email |
| `python3 embodied_daily.py --no-deliver` | Fetch → curate → archive only |
| `python3 embodied_daily.py --push-only` | Re-deliver the last digest from `latest.json` without fetching |

### Scheduled run on macOS (`launchd`)

```bash
bash install.sh   # creates config.json if missing, installs the Claude Code skill, registers a 09:30 launchd job
```

The installer also installs a [Claude Code](https://claude.com/claude-code) skill, so you can type `/embodied-daily` in Claude Code to trigger or inspect a run. `launchd` only runs while the Mac is awake; a missed run executes after wake.

### iPhone push with Bark

1. Install the free **Bark** app from the App Store.
2. Copy your device key — the `XXXXXX` part of `https://api.day.app/XXXXXX`.
3. Put it in `config.json` as `bark_key` (or the `BARK_KEY` secret on GitHub Actions).

## ☁️ Run in the cloud (GitHub Actions)

The bundled workflow [`daily.yml`](.github/workflows/daily.yml) runs every day at 01:30 UTC (09:30 Beijing time), curates with the Anthropic API, pushes to your phone, and commits the day's archive back to the repo — no machine of yours needs to be on.

1. Fork this repository.
2. **Settings → Secrets and variables → Actions → Secrets**, add:

   | Secret | Required | Description |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | ✅ for AI digests | Key from [console.anthropic.com](https://console.anthropic.com) (or from an API-compatible proxy, see `ANTHROPIC_BASE_URL`) |
   | `BARK_KEY` | for iPhone push | Your Bark device key |
   | `SMTP_PASSWORD` | for email | SMTP password / app password |

3. Optionally add **Variables**:

   | Variable | Description |
   |---|---|
   | `EMBODIED_INTERESTS` | e.g. `VLA, dexterous manipulation, world models` |
   | `EMBODIED_PUSH_PRIORITY` | tag keyword to push first, e.g. `Dexterous` |
   | `EMBODIED_LANGUAGE` | digest language, default `English` |
   | `ANTHROPIC_MODEL` | default `claude-sonnet-4-6` |
   | `ANTHROPIC_BASE_URL` | only for API-compatible proxies |
   | `EMAIL_TO`, `EMAIL_FROM`, `SMTP_HOST` | email delivery |

4. Open **Actions → Embodied AI Daily → Run workflow** once to verify.

> [!TIP]
> Without `ANTHROPIC_API_KEY` the workflow still succeeds but falls back to raw abstracts — look for `WARNING: AI curation unavailable` in the log. Scheduled GitHub Actions runs can be delayed by several minutes.

## ⚙️ Configuration

All options live in `config.json` (see [`config.example.json`](config.example.json)); environment variables override them.

| Key | Env override | Description | Default |
|---|---|---|---|
| `bark_key` | `BARK_KEY` | Bark device key; empty disables iPhone push | `""` |
| `bark_server` | `BARK_SERVER` | Bark server (change if self-hosted) | `https://api.day.app` |
| `top_n` | | Papers selected per day (all shown in the digest) | `10` |
| `push_n` | | Papers pushed to the phone (≤ `top_n`) | `5` |
| `push_priority` | `EMBODIED_PUSH_PRIORITY` | Phone push: papers whose tag contains this go first | `""` |
| `interests` | `EMBODIED_INTERESTS` | Your research interests, highest priority first | `""` |
| `language` | `EMBODIED_LANGUAGE` | Language of the generated digest | `English` |
| `same_day_only` | | Only the newest arXiv announcement day | `true` |
| `dedup_days` | | Skip papers archived in the last N days (0 = off) | `7` |
| `lookback_days` | | Days to look back when `same_day_only` is `false` | `3` |
| `max_candidates` | | Candidate pool size sent to the model | `40` |
| `queries` | | arXiv `search_query` strings | see file |
| `use_claude_cli` | | Enable AI curation (API first, then CLI) | `true` |
| `api_model` | `ANTHROPIC_MODEL` | Anthropic model | `claude-sonnet-4-6` |
| `api_base_url` | `ANTHROPIC_BASE_URL` | API base URL | `https://api.anthropic.com` |
| `api_retries` | | Retries on API failure | `3` |
| `claude_bin` | | Path to the `claude` CLI (empty = auto-detect) | `""` |
| `open_digest` | | macOS: open `latest.md` after a run | `true` |
| `email_to` | `EMAIL_TO` | Comma-separated recipients; empty disables email | `""` |
| `email_from` | `EMAIL_FROM` | Sender / SMTP account | `""` |
| `smtp_host` | `SMTP_HOST` | SMTP server | `""` |
| `smtp_port` | | `465` (SSL) or `587` (STARTTLS) | `465` |
| `smtp_password` | `SMTP_PASSWORD` | Prefer the env var over the file | `""` |
| `smtp_use_ssl` | | `true` = SSL, `false` = STARTTLS | `true` |

`config.json` is git-ignored — keep your keys there or in environment variables, never in tracked files.

## 🧱 How it works

```text
arXiv API (several queries)
        │  merge · de-dup · newest day · skip recently covered
        ▼
Claude (Anthropic API or local claude CLI)
        │  rank Top N · TL;DR · literature position · digest · highlights
        ▼
Markdown digest ──┬──▶ archive/DATE.md          (committed back by GitHub Actions)
                  ├──▶ latest.md / latest.json  (reused by --push-only)
                  ├──▶ Bark → iPhone            (one push per paper, top push_n)
                  ├──▶ macOS notification       (+ opens the full digest)
                  └──▶ Email                    (HTML attachment, optional)
```

## 📁 Repository layout

```text
embodied-daily/
├── embodied_daily.py          # the whole tool (stdlib only)
├── config.example.json        # configuration template → copy to config.json
├── install.sh                 # macOS: install Claude Code skill + launchd job
├── launchd/                   # launchd plist template
├── skill/SKILL.md             # Claude Code skill (/embodied-daily)
├── tests/                     # offline unit tests
├── archive/                   # daily digests (Markdown)
└── .github/workflows/         # daily.yml (digest) · ci.yml (tests)
```

## 📋 Requirements

- Python 3.9+ (the macOS system `/usr/bin/python3` works), standard library only
- `curl` (for Bark)
- For AI digests: an `ANTHROPIC_API_KEY`, or the [`claude` CLI](https://claude.com/claude-code)
- macOS only for `launchd`, desktop notifications and auto-open; everything else runs on any OS

## 🤝 Contributing

Issues and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Run the tests with:

```bash
python3 -m unittest discover -s tests -v
```

## 📝 License

[MIT](LICENSE). Paper titles, abstracts and links belong to their authors and arXiv. Generated digests are AI-written summaries and may contain mistakes — always check the original paper.
