#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Embodied AI Paper Digest
- Fetch recent embodied AI papers from arXiv
- Calls the local claude CLI for Chinese summaries / topic tags / Top5 ranking (reuses Claude subscription, no API key needed)
- Extract code repo links (falling back to GitHub / Papers with Code in the summary)
- Push to iPhone(Bark) + macOS notification, and archive as Markdown

Dependencies: Python standard library only + system curl. Optional claude CLI.
Config: config.json in the same directory
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
ARCHIVE_DIR = os.path.join(HERE, "archive")
LOG_PREFIX = "[embodied-daily]"

ATOM = "{http://www.w3.org/2005/Atom}"

DEFAULT_CONFIG = {
    "bark_key": "",                       # required: the key from the Bark app, e.g. XXXXXX in https://api.day.app/XXXXXX
    "bark_server": "https://api.day.app", # self-hosted Bark server can be changed
    "top_n": 10,                          # number of picks (Mac digest/archive shows all top_n)
    "push_n": 5,                          # push only the first push_n papers to iPhone (<= top_n)
    "interests": "",                      # personal interest preferences, related papers get priority and come first
    "same_day_only": True,                # True: only push papers from the latest announce day, never span multiple days
    "lookback_days": 3,                   # used when same_day_only=False: how many days to look back
    "max_candidates": 40,                 # max candidates sent to claude for ranking
    "queries": [
        "cat:cs.RO",
        "all:embodied",
        "all:%22vision-language-action%22",
        "all:%22robot+manipulation%22"
    ],
    "use_claude_cli": True,               # use local claude CLI for Chinese summaries; false = English only
    "claude_bin": "",                     # leave empty to auto-detect; an absolute path also works, e.g. /Users/xxx/.local/bin/claude
    "open_digest": True                   # automatically open the day's digest latest.md with the default app after the run (Mac)
}


def log(*a):
    print(LOG_PREFIX, datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("Failed to parse config.json, using defaults:", e)
    return cfg


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "embodied-daily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------- arXiv fetching ----------------

def fetch_query(query, max_results):
    url = (
        "https://export.arxiv.org/api/query?search_query=" + query +
        "&sortBy=submittedDate&sortOrder=descending&max_results=" + str(max_results)
    )
    try:
        return http_get(url)
    except Exception as e:
        log("arXiv query failed:", query, e)
        return ""


def parse_atom(xml_text):
    out = []
    if not xml_text.strip():
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        log("XML parse failed:", e)
        return out
    for entry in root.findall(ATOM + "entry"):
        def text(tag):
            el = entry.find(ATOM + tag)
            return (el.text or "").strip() if el is not None else ""
        arxiv_url = text("id")
        m = re.search(r"arxiv\.org/abs/([0-9]+\.[0-9]+)", arxiv_url)
        aid = m.group(1) if m else arxiv_url
        title = re.sub(r"\s+", " ", text("title")).strip()
        summary = re.sub(r"\s+", " ", text("summary")).strip()
        published = text("published")
        authors = [a.findtext(ATOM + "name", "").strip()
                   for a in entry.findall(ATOM + "author")]
        pdf_url = ""
        for link in entry.findall(ATOM + "link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        github = ""
        gm = re.search(r"https?://github\.com/[\w.\-]+/[\w.\-]+", summary)
        if gm:
            github = gm.group(0).rstrip(".")
        out.append({
            "id": aid,
            "title": title,
            "summary": summary,
            "published": published,
            "authors": authors,
            "abs_url": "https://arxiv.org/abs/" + aid if m else arxiv_url,
            "pdf_url": pdf_url,
            "github": github,
        })
    return out


def recent_enough(published, lookback_days):
    try:
        dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=lookback_days)


def gather_candidates(cfg):
    seen = {}
    for q in cfg["queries"]:
        papers = parse_atom(fetch_query(q, cfg["max_candidates"]))
        for p in papers:
            if p["id"] not in seen:
                seen[p["id"]] = p
    cand = list(seen.values())
    cand.sort(key=lambda p: p.get("published", ""), reverse=True)
    if cfg.get("same_day_only", True):
        # same-day only: keep only papers from the latest announcement day, no multi-day span (do not backfill even if fewer than top_n)
        dates = [p["published"][:10] for p in cand if p.get("published")]
        if dates:
            newest = max(dates)
            pool = [p for p in cand if p.get("published", "")[:10] == newest]
            log("today's batch:", newest, "papers:", len(pool))
        else:
            pool = cand
    else:
        # Look back lookback days; if fewer than top_n, backfill with older ones
        recent = [p for p in cand if recent_enough(p["published"], cfg["lookback_days"])]
        pool = recent if len(recent) >= cfg["top_n"] else cand
    return pool[: cfg["max_candidates"]]


# ---------------- Papers with Code fallback for code lookup ----------------

def pwc_code(arxiv_id):
    try:
        url = "https://paperswithcode.com/api/v1/papers/%s/repositories/" % arxiv_id
        data = json.loads(http_get(url, timeout=15))
        results = data.get("results") or []
        if results:
            return results[0].get("url", "")
    except Exception:
        pass
    return ""


# ---------------- claude CLI Chinese summary/tags/ranking ----------------

def find_claude_bin(cfg):
    if cfg.get("claude_bin"):
        return cfg["claude_bin"]
    for p in [os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if os.path.exists(p):
            return p
    # PATH probe
    try:
        out = subprocess.run(["which", "claude"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def claude_curate(cfg, candidates):
    """Return [{idx, zh_summary, tag}] (idx is an index into candidates), or None on failure"""
    claude_bin = find_claude_bin(cfg)
    if not claude_bin:
        log("claude CLI not found, skipping AI summaries")
        return None
    listing = []
    for i, p in enumerate(candidates):
        abs = p["summary"][:1100]
        listing.append("[%d] Title: %s\nAbstract: %s" % (i, p["title"], abs))
    # optional: reader interests (from interests in config.json), used to shape selection and ranking
    interests = str(cfg.get("interests", "")).strip()
    interest_line = ""
    if interests:
        interest_line = (
            "[Reader preference] My personal focus: %s. Prioritize papers related to these areas,"
            "and rank them higher; but if other embodied work that day is clearly more important, they may still be included.\n" % interests
        )
    head = (
        "You are a senior research assistant in Embodied AI. Below are several arXiv paper candidates.\n"
        "Please pick the %d most relevant and valuable papers on [Embodied AI] (covering areas such as VLA, robot manipulation/grasping,"
        "navigation, humanoid robots, dexterous hands, sim-to-real, world models, RL control, etc.).\n" % cfg["top_n"]
    )
    body = (
        "For each paper produce a detailed write-up in Chinese, covering these fields:\n"
        "- tag: short Chinese topic tag (e.g. VLA / dexterous hands / world model)\n"
        "- tldr: one-line highlight (20-30 chars, so the point is obvious at a glance)\n"
        "- zh_summary: a detailed summary (5-8 sentences), covering in order: (1) the problem or pain point the research addresses "
        "(2) method/core idea (3) main innovations (4) experimental results or performance (5) why it matters/application value\n"
        "- highlights: 2-4 key points (array, each at most 25 words, distilling key contributions or numeric results)\n"
        "Use plain, accurate language for readers with an AI background; avoid piling up English jargon.\n"
        "Output strictly a single JSON array, no extra text, no markdown code blocks.\n"
        "Format: [{\"idx\": candidate index (integer), \"tag\": \"...\", \"tldr\": \"...\", "
        "\"zh_summary\": \"...\", \"highlights\": [\"...\", \"...\"]}]\n"
        "Sort by importance from high to low, exactly %d elements.\n\nCandidate list:\n%s"
        % (cfg["top_n"], "\n\n".join(listing))
    )
    prompt = head + interest_line + body
    try:
        log("calling claude CLI to generate Chinese summaries (may take 1-2 minutes)...")
        proc = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        if proc.returncode != 0:
            log("claude CLI returned non-zero:", proc.stderr[:300])
            return None
        raw = proc.stdout.strip()
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            log("claude output has no JSON array")
            return None
        arr = json.loads(m.group(0))
        cleaned = []
        for item in arr:
            idx = int(item.get("idx", -1))
            if 0 <= idx < len(candidates):
                hl = item.get("highlights", [])
                if not isinstance(hl, list):
                    hl = [str(hl)]
                cleaned.append({
                    "idx": idx,
                    "tag": str(item.get("tag", "embodied AI")).strip(),
                    "tldr": str(item.get("tldr", "")).strip(),
                    "zh_summary": str(item.get("zh_summary", "")).strip(),
                    "highlights": [str(x).strip() for x in hl if str(x).strip()],
                })
        return cleaned[: cfg["top_n"]] or None
    except subprocess.TimeoutExpired:
        log("claude CLI timed out")
        return None
    except Exception as e:
        log("claude CLI call failed:", e)
        return None


KEYWORD_TAGS = [
    ("vision-language-action", "VLA"), ("vla", "VLA"),
    ("manipulat", "robot manipulation"), ("grasp", "grasping"),
    ("navigat", "Navigation"), ("humanoid", "Humanoid Robots"),
    ("dexterous", "dexterous hands"), ("sim-to-real", "Sim2Real"),
    ("world model", "world model"), ("locomot", "motion control"),
    ("reinforcement", "reinforcement learning"), ("embodied", "embodied AI"),
]


def keyword_tag(text):
    low = text.lower()
    for kw, tag in KEYWORD_TAGS:
        if kw in low:
            return tag
    return "Embodied AI"


def build_items(cfg, candidates):
    curated = claude_curate(cfg, candidates) if cfg.get("use_claude_cli") else None
    items = []
    if curated:
        for c in curated:
            p = candidates[c["idx"]]
            items.append({
                "paper": p,
                "tag": c["tag"],
                "tldr": c.get("tldr", ""),
                "zh_summary": c["zh_summary"],
                "highlights": c.get("highlights", []),
            })
    else:
        log("using keyword fallback mode (English abstracts)")
        for p in candidates[: cfg["top_n"]]:
            items.append({
                "paper": p,
                "tag": keyword_tag(p["title"] + " " + p["summary"]),
                "tldr": "",
                "zh_summary": "(AI summary not enabled) " + p["summary"][:400],
                "highlights": [],
            })
    # Fill in code links
    for it in items:
        p = it["paper"]
        code = p.get("github") or pwc_code(p["id"]) or "not available"
        it["code"] = code
    return items


# ---------------- output: Markdown / Bark / macOS ----------------

def render_markdown(items, date_str):
    lines = ["# Embodied AI Top%d (Today) · %s\n" % (len(items), date_str),
             "> Daily automatic fetch of the latest Embodied AI papers from arXiv, with AI-curated commentary.\n"]
    for i, it in enumerate(items, 1):
        p = it["paper"]
        lines.append("## %d. 【%s】%s" % (i, it["tag"], p["title"]))
        if it.get("tldr"):
            lines.append("\n> 💡 %s\n" % it["tldr"])
        if p.get("authors"):
            lines.append("**Authors**: " + ", ".join(p["authors"][:6]) +
                         (" et al." if len(p["authors"]) > 6 else ""))
        lines.append("\n" + it["zh_summary"] + "\n")
        if it.get("highlights"):
            lines.append("**Highlights**:")
            for h in it["highlights"]:
                lines.append("- " + h)
            lines.append("")
        lines.append("**Links**:")
        lines.append("- 📄 arXiv: %s" % p["abs_url"])
        lines.append("- 📕 PDF: %s" % (p.get("pdf_url") or "—"))
        lines.append("- 💻 Code: %s" % it["code"])
        lines.append("")
    return "\n".join(lines)


def render_push_body(items):
    # single push: each paper has tags+title+one-line highlight+key points+link; see the Markdown archive for the full long-form write-up
    parts = []
    for i, it in enumerate(items, 1):
        p = it["paper"]
        seg = ["%d.【%s】%s" % (i, it["tag"], p["title"])]
        if it.get("tldr"):
            seg.append("💡 " + it["tldr"])
        hl = it.get("highlights") or []
        if hl:
            seg.append("· " + " · ".join(hl[:2]))
        seg.append("📄 " + p["abs_url"])
        parts.append("\n".join(seg))
    return "\n\n".join(parts)


def _truncate(s, limit=3200):
    if len(s.encode("utf-8")) <= limit:
        return s
    # Byte-safe truncation
    out = s
    while len(out.encode("utf-8")) > limit - 3:
        out = out[:-1]
    return out + "…"


def push_bark(cfg, title, body):
    key = cfg.get("bark_key", "").strip()
    if not key:
        log("bark_key not configured, skipping iPhone push (please fill it in config.json)")
        return
    url = cfg["bark_server"].rstrip("/") + "/" + key
    payload = json.dumps({
        "title": title, "body": _truncate(body), "group": "Embodied Daily", "sound": "birdsong"
    }, ensure_ascii=False)
    # push via system curl (more reliable TLS to Bark than urllib)
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "25", "-X", "POST", url,
             "-H", "Content-Type: application/json; charset=utf-8",
             "-d", payload],
            capture_output=True, text=True, timeout=30,
        )
        msg = proc.stdout.strip() or proc.stderr.strip()
        log("Bark push:", msg[:200])
    except Exception as e:
        log("Bark push failed:", e)


def _as_str(s):
    # AppleScript string: keep Chinese as-is (cannot use \uXXXX), escape backslashes and double quotes, strip newlines
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", " ").replace("\n", " ")
    return '"' + s + '"'


def notify_macos(title, subtitle, msg):
    try:
        script = "display notification %s with title %s subtitle %s" % (
            _as_str(msg), _as_str(title), _as_str(subtitle))
        subprocess.run(["osascript", "-e", script], timeout=15)
    except Exception as e:
        log("macOS notification failed:", e)


def push_digest(cfg, items, date_str):
    """Push one full detailed write-up per paper (N total, each within the Bark limit)"""
    if not cfg.get("bark_key", "").strip():
        log("bark_key not configured, skipping iPhone push (please fill it in config.json)")
        return
    n = len(items)
    for i, it in enumerate(items, 1):
        p = it["paper"]
        title = "📚 %d/%d today embodied - %s" % (i, n, date_str)
        lines = ["【%s】%s" % (it["tag"], p["title"])]
        if it.get("tldr"):
            lines.append("💡 " + it["tldr"])
        lines.append("")
        lines.append(it["zh_summary"])
        if it.get("highlights"):
            lines.append("")
            lines.append("✨ Highlights:")
            for h in it["highlights"]:
                lines.append("· " + h)
        lines.append("")
        lines.append("📄 arXiv: " + p["abs_url"])
        lines.append("💻 Code: " + it["code"])
        push_bark(cfg, title, "\n".join(lines))


def main():
    cfg = load_config()
    date_str = datetime.now().strftime("%Y-%m-%d")
    log("Fetching candidates...")
    candidates = gather_candidates(cfg)
    log("candidate count:", len(candidates))
    if not candidates:
        push_bark(cfg, "📚 Embodied AI Today", "No papers fetched today (arXiv may have no updates)")
        log("no candidates, exiting")
        return
    items = build_items(cfg, candidates)
    log("final paper count:", len(items))

    md = render_markdown(items, date_str)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    md_path = os.path.join(ARCHIVE_DIR, date_str + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    # also maintain latest.md and the structured latest.json (reused by --push-only)
    with open(os.path.join(HERE, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(HERE, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "items": items}, f, ensure_ascii=False, indent=2)
    log("Archived:", md_path)

    deliver(cfg, items, date_str)
    log("Done")


def deliver(cfg, items, date_str):
    """Push/notify/open: on iPhone push only the first push_n papers; Mac notifies and opens the digest with all top_n papers"""
    # iPhone: only push the first push_n papers (default 5); Mac/archive: all top_n papers (default 10)
    push_n = min(int(cfg.get("push_n", 5)), len(items))
    push_digest(cfg, items[:push_n], date_str)
    # One combined Mac desktop notification (lists all top_n titles)
    titles = "  ".join("%d.%s" % (i, it["paper"]["title"][:24])
                       for i, it in enumerate(items, 1))
    notify_macos("📚 Today's Embodied AI Top%d · %s (push top %d to phone)" % (len(items), date_str, push_n),
                 " / ".join(dict.fromkeys(it["tag"] for it in items)),
                 titles)
    # Open today's digest with the default program (clicking the native Mac notification does nothing, so this is a fallback)
    if cfg.get("open_digest", True):
        try:
            subprocess.run(["open", os.path.join(HERE, "latest.md")], timeout=15)
        except Exception as e:
            log("Failed to open digest:", e)


def push_only():
    """Read the previously generated latest.json and re-push it directly, without re-fetching or calling claude"""
    cfg = load_config()
    path = os.path.join(HERE, "latest.json")
    if not os.path.exists(path):
        log("no latest.json found, please do a normal run first")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    log("Re-push from latest.json, paper count:", len(items))
    deliver(cfg, items, date_str)
    log("Done")


if __name__ == "__main__":
    try:
        if "--push-only" in sys.argv:
            push_only()
        else:
            main()
    except Exception as e:
        log("Fatal error:", repr(e))
        sys.exit(1)
