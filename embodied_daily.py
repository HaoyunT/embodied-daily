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
import time
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
    "dedup_days": 7,                       # exclude papers already pushed in the last N days (dedupe by archive), 0 disables
    "lookback_days": 3,                   # used when same_day_only=False: how many days to look back
    "max_candidates": 40,                 # max candidates sent to claude for ranking
    "queries": [
        "cat:cs.RO",
        "all:embodied",
        "all:%22vision-language-action%22",
        "all:%22robot+manipulation%22"
    ],
    "use_claude_cli": True,               # use claude (API first, otherwise CLI) for Chinese summaries; false gives English summaries only
    "api_model": "claude-sonnet-4-6",     # model used for the cloud Anthropic API (can be overridden by the ANTHROPIC_MODEL env var)
    "api_base_url": "https://api.anthropic.com",  # can be overridden by ANTHROPIC_BASE_URL (third-party relay: put its address here)
    "api_retries": 3,                     # Retries when an API call fails (fallback for occasional dropped connections via proxy)
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
    # Environment variable overrides (for cloud/CI without config.json)
    if os.environ.get("BARK_KEY", "").strip():
        cfg["bark_key"] = os.environ["BARK_KEY"].strip()
    if os.environ.get("BARK_SERVER", "").strip():
        cfg["bark_server"] = os.environ["BARK_SERVER"].strip()
    if os.environ.get("EMBODIED_INTERESTS", "").strip():
        cfg["interests"] = os.environ["EMBODIED_INTERESTS"].strip()
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


def recent_pushed_ids(days):
    """Collect arXiv ids already pushed from the archived md files of the last days (excluding today), used for deduplication"""
    ids = set()
    if days <= 0 or not os.path.isdir(ARCHIVE_DIR):
        return ids
    today = datetime.now().date()
    for fn in os.listdir(ARCHIVE_DIR):
        if not fn.endswith(".md"):
            continue
        try:
            d = datetime.strptime(fn[:-3], "%Y-%m-%d").date()
        except Exception:
            continue
        delta = (today - d).days
        if 0 < delta <= days:   # Past days only, excluding today (same-day rerun allowed)
            try:
                with open(os.path.join(ARCHIVE_DIR, fn), "r", encoding="utf-8") as f:
                    text = f.read()
                for mid in re.findall(r"arxiv\.org/abs/([0-9]+\.[0-9]+)", text):
                    ids.add(mid)
            except Exception:
                pass
    return ids


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
    # Dedupe: exclude papers already pushed in the last dedup_days days, so every day brings fresh content
    dedup_days = int(cfg.get("dedup_days", 0))
    if dedup_days > 0:
        seen_ids = recent_pushed_ids(dedup_days)
        before = len(pool)
        pool = [p for p in pool if p["id"] not in seen_ids]
        if before != len(pool):
            log("dedupe: last %d days, excluded %d already-pushed papers, %d left" % (dedup_days, before - len(pool), len(pool)))
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


def build_curate_prompt(cfg, candidates):
    """Build the selection + commentary prompt (PaperLocus style: literature positioning + claim vs inference distinction)"""
    listing = []
    for i, p in enumerate(candidates[:30]):   # send at most 30 candidates, to keep the request body small
        abs = p["summary"][:800]
        listing.append("[%d] Title: %s\nAbstract: %s" % (i, p["title"], abs))
    interests = str(cfg.get("interests", "")).strip()
    interest_line = ""
    if interests:
        interest_line = (
            "[Reader preferences - highest to lowest priority] My main focus: %s."
            "The earlier in the list, the higher the priority: for the direction ranked first, if there are related papers that day, be sure to include them and place them first; "
            "Also rank related work in other directions as high as possible. But if there is clearly more important other embodied work that day, still include it.\n" % interests
        )
    head = (
        "You are a senior research assistant in the Embodied AI field, skilled at interpreting papers within their literature context (follow the PaperLocus reading style).\n"
        "Below are several arXiv paper candidates (titles and abstracts only).\n"
        "Please pick the %d most relevant and valuable papers on [Embodied AI] (covering areas such as VLA, robot manipulation/grasping,"
        "navigation, humanoid robots, dexterous hands, sim-to-real, world models, RL control, etc.).\n" % cfg["top_n"]
    )
    body = (
        "Produce a structured Chinese analysis for each paper, including the following fields:\n"
        "- tag: short Chinese topic tag (e.g. VLA / dexterous hands / world model)\n"
        "- tldr: one-line highlight (20-30 chars, so the point is obvious at a glance)\n"
        "- position: paper positioning (1-2 sentences), use the frame of \"modify B on top of A, thus obtaining C\", "
        "and state which kind of prior work/baseline it mainly compares against, and which research line it belongs to\n"
        "- zh_summary: detailed commentary (5-8 sentences), covering in order: 1) the problem/pain point the research addresses "
        "2) Method / core idea 3) Main innovations 4) Experimental design and key results (include numbers where available) 5) Value, scope of applicability and limitations."
        "Use only information available in the abstracts; do not invent data, baselines, code or conclusions not mentioned; "
        "If it is an inference rather than an explicit claim in the paper, mark it with \"speculation/possible\".\n"
        "- highlights: 2-4 key points (array, each at most 25 words, distilling key contributions or numeric results)\n"
        "plain and accurate language for readers with an AI background, no piling up of English jargon.\n"
        "[Output format requirement - must follow strictly] Output only one valid JSON array that can be parsed by json.loads, "
        "no extra text, no markdown code blocks."
        "Inside string values, English double quotes (\") and newlines are forbidden; to quote a term, use single quotes '' instead, "
        "Write English terms/abbreviations as-is, without quotes.\n"
        "Format: [{\"idx\": candidate index (integer), \"tag\": \"...\", \"tldr\": \"...\", "
        "\"position\": \"...\", \"zh_summary\": \"...\", \"highlights\": [\"...\", \"...\"]}]\n"
        "Sort by importance from high to low, exactly %d elements.\n\nCandidate list:\n%s"
        % (cfg["top_n"], "\n\n".join(listing))
    )
    return head + interest_line + body


def parse_curate_response(raw, candidates, cfg):
    """Extract the JSON array from the raw model output and clean it (with tolerant repair)"""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        log("No JSON array found in model output")
        return None
    blob = m.group(0)
    try:
        arr = json.loads(blob)
    except Exception:
        # Fault tolerance: strip bare control chars (newline/tab) that may be unescaped in the string, then retry
        repaired = blob.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        try:
            arr = json.loads(repaired)
            log("JSON parsed successfully after fault-tolerant repair")
        except Exception as e:
            log("JSON parse failed (still failing after repair):", e)
            return None
    cleaned = []
    for item in arr:
        idx = int(item.get("idx", -1))
        if 0 <= idx < len(candidates):
            hl = item.get("highlights", [])
            if not isinstance(hl, list):
                hl = [str(hl)]
            cleaned.append({
                "idx": idx,
                "tag": str(item.get("tag", "Embodied AI")).strip(),
                "tldr": str(item.get("tldr", "")).strip(),
                "position": str(item.get("position", "")).strip(),
                "zh_summary": str(item.get("zh_summary", "")).strip(),
                "highlights": [str(x).strip() for x in hl if str(x).strip()],
            })
    return cleaned[: cfg["top_n"]] or None


def curate_via_api(cfg, candidates):
    """Use the Anthropic API for selection + analysis (cloud / no claude CLI), with retries; return None on failure"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("ANTHROPIC_MODEL") or cfg.get("api_model", "claude-sonnet-4-6")
    base = (os.environ.get("ANTHROPIC_BASE_URL")
            or cfg.get("api_base_url", "https://api.anthropic.com")).rstrip("/")
    prompt = build_curate_prompt(cfg, candidates)
    payload = json.dumps({
        "model": model,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    attempts = int(cfg.get("api_retries", 3))
    for i in range(1, attempts + 1):
        req = urllib.request.Request(
            base + "/v1/messages", data=payload,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            log("Calling Anthropic API to generate Chinese summary (model %s, attempt %d/%d)..." % (model, i, attempts))
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            raw = "".join(b.get("text", "") for b in data.get("content", []))
            result = parse_curate_response(raw, candidates, cfg)
            if result:
                return result
            log("Parsed result is empty, retrying...")
        except Exception as e:
            log("Anthropic API call failed (attempt %d):" % i, e)
        if i < attempts:
            time.sleep(5)
    return None


def curate_via_cli(cfg, candidates):
    """Use the local claude CLI for selection + analysis (reuses the Claude subscription); return None on failure"""
    claude_bin = find_claude_bin(cfg)
    if not claude_bin:
        return None
    prompt = build_curate_prompt(cfg, candidates)
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
        return parse_curate_response(proc.stdout.strip(), candidates, cfg)
    except subprocess.TimeoutExpired:
        log("claude CLI timed out")
        return None
    except Exception as e:
        log("claude CLI call failed:", e)
        return None


def curate(cfg, candidates):
    """Smart selection + commentary: prefer the Anthropic API (cloud), else the local claude CLI; return None if neither works"""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        result = curate_via_api(cfg, candidates)
        if result:
            return result
        log("API route failed, trying the local claude CLI...")
    return curate_via_cli(cfg, candidates)


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
    curated = curate(cfg, candidates) if cfg.get("use_claude_cli", True) else None
    items = []
    if curated:
        for c in curated:
            p = candidates[c["idx"]]
            items.append({
                "paper": p,
                "tag": c["tag"],
                "tldr": c.get("tldr", ""),
                "position": c.get("position", ""),
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
                "position": "",
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
             "> Auto-fetches the latest arXiv Embodied AI papers daily, with AI-curated reviews (PaperLocus style).\n"]
    for i, it in enumerate(items, 1):
        p = it["paper"]
        lines.append("## %d. 【%s】%s" % (i, it["tag"], p["title"]))
        if it.get("tldr"):
            lines.append("\n> 💡 %s\n" % it["tldr"])
        if p.get("authors"):
            lines.append("**Authors**: " + ", ".join(p["authors"][:6]) +
                         (" et al." if len(p["authors"]) > 6 else ""))
        if it.get("position"):
            lines.append("\n**🧭 Literature positioning**: " + it["position"])
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
