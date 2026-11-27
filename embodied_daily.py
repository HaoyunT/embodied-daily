#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embodied-daily: a daily digest of new Embodied AI papers from arXiv.

Pipeline:
  1. Fetch the latest embodied-AI-related papers from several arXiv queries.
  2. Ask Claude (Anthropic API, or the local `claude` CLI) to pick the top N,
     rank them, and write a structured digest for each paper.
  3. Find code links (GitHub URL in the abstract, Papers with Code fallback).
  4. Deliver: Bark push to iPhone, macOS notification, optional email,
     and a Markdown archive under archive/.

Dependencies: Python 3 standard library + system `curl`. The `claude` CLI is optional.
Configuration: config.json next to this file, overridable by environment variables
(see config.example.json and README.md).
"""

import argparse
import email.mime.application
import email.mime.multipart
import email.mime.text
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
ARCHIVE_DIR = os.path.join(HERE, "archive")
LOG_PREFIX = "[embodied-daily]"
IS_MACOS = sys.platform == "darwin"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_ID_RE = r"arxiv\.org/abs/([0-9]+\.[0-9]+)"
DEFAULT_TAG = "Embodied AI"
NO_CODE = "N/A"
ARXIV_DELAY_S = 3  # arXiv asks for ~3 s between API calls

DEFAULT_CONFIG = {
    "bark_key": "",                        # Bark device key: the XXXXXX in https://api.day.app/XXXXXX
    "bark_server": "https://api.day.app",  # change if you self-host Bark
    "top_n": 10,                           # papers selected per day (all shown in the Markdown digest)
    "push_n": 5,                           # only the first push_n papers are pushed to the phone (<= top_n)
    "push_priority": "",                   # phone push: papers whose tag contains this keyword go first
    "interests": "",                       # research interests, highest priority first, e.g. "VLA, dexterous hands"
    "language": "English",                 # language of the generated digest, e.g. "English", "Chinese"
    "same_day_only": True,                 # only keep papers from the newest arXiv announcement day
    "dedup_days": 7,                       # skip papers already archived in the last N days; 0 disables
    "lookback_days": 3,                    # used when same_day_only is false
    "max_candidates": 40,                  # size of the candidate pool sent to the model
    "queries": [
        "cat:cs.RO",
        "all:embodied",
        "all:%22vision-language-action%22",
        "all:%22robot+manipulation%22"
    ],
    "use_claude_cli": True,                # enable AI curation (API first, then local CLI); false = abstracts only
    "api_model": "claude-sonnet-4-6",      # overridable by ANTHROPIC_MODEL
    "api_base_url": "https://api.anthropic.com",  # overridable by ANTHROPIC_BASE_URL
    "api_retries": 3,                      # retries for flaky API connections
    "claude_bin": "",                      # path to the claude CLI; empty = auto-detect
    "open_digest": True,                   # macOS: open latest.md after a run
    "email_to": "",                        # comma-separated recipients; non-empty enables email delivery
    "email_from": "",                      # SMTP account / sender address
    "smtp_host": "",                       # e.g. smtp.gmail.com
    "smtp_port": 465,                      # 465 = SSL, 587 = STARTTLS
    "smtp_password": "",                   # prefer the SMTP_PASSWORD env var
    "smtp_use_ssl": True                   # True = SSL (465), False = STARTTLS (587)
}

# Environment variable -> config key (used by CI, where there is no config.json).
ENV_OVERRIDES = {
    "BARK_KEY": "bark_key",
    "BARK_SERVER": "bark_server",
    "EMBODIED_INTERESTS": "interests",
    "EMBODIED_PUSH_PRIORITY": "push_priority",
    "EMBODIED_LANGUAGE": "language",
    "EMAIL_TO": "email_to",
    "EMAIL_FROM": "email_from",
    "SMTP_HOST": "smtp_host",
    "SMTP_PASSWORD": "smtp_password",
}


def log(*a):
    print(LOG_PREFIX, datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def load_config(path=CONFIG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("Failed to parse config.json, using defaults:", e)
    for env, key in ENV_OVERRIDES.items():
        val = os.environ.get(env, "").strip()
        if val:
            cfg[key] = val
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
        log("Failed to parse arXiv XML:", e)
        return out
    for entry in root.findall(ATOM + "entry"):
        def text(tag):
            el = entry.find(ATOM + tag)
            return (el.text or "").strip() if el is not None else ""
        arxiv_url = text("id")
        m = re.search(ARXIV_ID_RE, arxiv_url)
        aid = m.group(1) if m else arxiv_url
        title = re.sub(r"\s+", " ", text("title")).strip()
        summary = re.sub(r"\s+", " ", text("summary")).strip()
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
            "published": text("published"),
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


def recent_pushed_ids(days, archive_dir=ARCHIVE_DIR, today=None):
    """arXiv ids found in archives from the last `days` days (excluding today), for dedup."""
    ids = set()
    if days <= 0 or not os.path.isdir(archive_dir):
        return ids
    today = today or datetime.now().date()
    for fn in os.listdir(archive_dir):
        if not fn.endswith(".md"):
            continue
        try:
            d = datetime.strptime(fn[:-3], "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 < (today - d).days <= days:  # past days only, so re-running today still works
            try:
                with open(os.path.join(archive_dir, fn), "r", encoding="utf-8") as f:
                    ids.update(re.findall(ARXIV_ID_RE, f.read()))
            except Exception:
                pass
    return ids


def gather_candidates(cfg):
    seen = {}
    for i, q in enumerate(cfg["queries"]):
        if i:
            time.sleep(ARXIV_DELAY_S)  # arXiv API etiquette: avoids HTTP 429
        for p in parse_atom(fetch_query(q, cfg["max_candidates"])):
            seen.setdefault(p["id"], p)
    cand = sorted(seen.values(), key=lambda p: p.get("published", ""), reverse=True)
    if cfg.get("same_day_only", True):
        # Keep only the newest announcement day; never backfill from earlier days.
        dates = [p["published"][:10] for p in cand if p.get("published")]
        if dates:
            newest = max(dates)
            pool = [p for p in cand if p.get("published", "")[:10] == newest]
            log("Newest batch:", newest, "papers:", len(pool))
        else:
            pool = cand
    else:
        # Look back lookback_days; if that is not enough, fall back to everything fetched.
        recent = [p for p in cand if recent_enough(p["published"], cfg["lookback_days"])]
        pool = recent if len(recent) >= cfg["top_n"] else cand
    dedup_days = int(cfg.get("dedup_days", 0))
    if dedup_days > 0:
        seen_ids = recent_pushed_ids(dedup_days)
        before = len(pool)
        pool = [p for p in pool if p["id"] not in seen_ids]
        if before != len(pool):
            log("Dedup: dropped %d papers seen in the last %d days, %d left"
                % (before - len(pool), dedup_days, len(pool)))
    return pool[: cfg["max_candidates"]]


# ---------------- Papers with Code fallback ----------------

def pwc_code(arxiv_id):
    try:
        url = "https://paperswithcode.com/api/v1/papers/%s/repositories/" % arxiv_id
        results = json.loads(http_get(url, timeout=15)).get("results") or []
        if results:
            return results[0].get("url", "")
    except Exception:
        pass
    return ""


# ---------------- Claude curation ----------------

def find_claude_bin(cfg):
    if cfg.get("claude_bin"):
        return cfg["claude_bin"]
    for p in [os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if os.path.exists(p):
            return p
    try:
        out = subprocess.run(["which", "claude"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def build_curate_prompt(cfg, candidates):
    """Curation prompt: select + rank + digest, positioning each paper in the literature."""
    listing = []
    for i, p in enumerate(candidates[:30]):  # cap at 30 candidates to bound the request size
        listing.append("[%d] Title: %s\nAbstract: %s" % (i, p["title"], p["summary"][:800]))
    language = str(cfg.get("language") or "English").strip()
    interests = str(cfg.get("interests", "")).strip()
    interest_line = ""
    if interests:
        interest_line = (
            "Reader interests, highest priority first: %s. "
            "If there are papers on the first interest today, include them and rank them at the top; "
            "papers on the other interests should also rank high. Clearly more important embodied-AI "
            "work on other topics may still be included.\n" % interests
        )
    head = (
        "You are a senior research assistant in Embodied AI who explains papers by placing them "
        "in the context of prior work.\n"
        "Below are arXiv paper candidates (title + abstract only).\n"
        "Select the %d papers most relevant and valuable to Embodied AI (e.g. VLA, robot "
        "manipulation/grasping, navigation, humanoids, dexterous hands, sim-to-real, world models, "
        "RL for control).\n" % cfg["top_n"]
    )
    body = (
        "For each selected paper, produce a structured digest with these fields:\n"
        "- tag: a short research-area tag (e.g. VLA / Dexterous Hands / World Models)\n"
        "- tldr: a one-sentence highlight (at most ~25 words) that says why the paper matters\n"
        "- position: 1-2 sentences placing it in the literature, framed as \"builds on A, changes B, "
        "achieving C\", naming which prior work / baselines it is compared against\n"
        "- digest: a detailed explanation (5-8 sentences) covering in order: (1) the problem, "
        "(2) the method, (3) the key novelty, (4) experiments and key results (include numbers if "
        "given), (5) value, scope and limitations. Use only information available in the abstract; "
        "do not invent numbers, baselines, code or conclusions. Mark inferences that the paper does "
        "not state explicitly with \"likely\" or \"possibly\".\n"
        "- highlights: 2-4 bullet points (array, each at most ~15 words) with key contributions or "
        "numeric results\n"
        "Write every text field in %s, clearly and accurately, for readers with an AI background.\n"
        "OUTPUT FORMAT (strict): output only a single JSON array parseable by json.loads, with no "
        "other text and no markdown code fences. String values must not contain double quotes or "
        "newlines; use single quotes if you need to quote a term.\n"
        "Format: [{\"idx\": candidate number (integer), \"tag\": \"...\", \"tldr\": \"...\", "
        "\"position\": \"...\", \"digest\": \"...\", \"highlights\": [\"...\", \"...\"]}]\n"
        "Order by importance, most important first, with exactly %d elements.\n\nCandidates:\n%s"
        % (language, cfg["top_n"], "\n\n".join(listing))
    )
    return head + interest_line + body


def parse_curate_response(raw, candidates, cfg):
    """Extract and clean the JSON array from raw model output (with light repair)."""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        log("No JSON array found in model output")
        return None
    blob = m.group(0)
    try:
        arr = json.loads(blob)
    except Exception:
        # Repair: drop raw control characters (newlines/tabs) inside strings and retry.
        repaired = blob.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        try:
            arr = json.loads(repaired)
            log("JSON parsed after repair")
        except Exception as e:
            log("JSON parse failed even after repair:", e)
            return None
    cleaned = []
    for item in arr:
        try:
            idx = int(item.get("idx", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(candidates):
            hl = item.get("highlights", [])
            if not isinstance(hl, list):
                hl = [str(hl)]
            cleaned.append({
                "idx": idx,
                "tag": str(item.get("tag", DEFAULT_TAG)).strip(),
                "tldr": str(item.get("tldr", "")).strip(),
                "position": str(item.get("position", "")).strip(),
                "digest": str(item.get("digest") or item.get("zh_summary") or "").strip(),
                "highlights": [str(x).strip() for x in hl if str(x).strip()],
            })
    return cleaned[: cfg["top_n"]] or None


def curate_via_api(cfg, candidates):
    """Curate with the Anthropic Messages API (CI / no CLI), with retries. Returns None on failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("ANTHROPIC_MODEL") or cfg.get("api_model", "claude-sonnet-4-6")
    base = (os.environ.get("ANTHROPIC_BASE_URL")
            or cfg.get("api_base_url", "https://api.anthropic.com")).rstrip("/")
    payload = json.dumps({
        "model": model,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": build_curate_prompt(cfg, candidates)}],
    }).encode("utf-8")
    attempts = int(cfg.get("api_retries", 3))
    for i in range(1, attempts + 1):
        req = urllib.request.Request(
            base + "/v1/messages", data=payload,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            log("Calling Anthropic API (model %s, attempt %d/%d)..." % (model, i, attempts))
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            raw = "".join(b.get("text", "") for b in data.get("content", []))
            result = parse_curate_response(raw, candidates, cfg)
            if result:
                return result
            log("Empty parse result, retrying...")
        except Exception as e:
            log("Anthropic API call failed (attempt %d):" % i, e)
        if i < attempts:
            time.sleep(5)
    return None


def curate_via_cli(cfg, candidates):
    """Curate with the local `claude` CLI (uses your Claude login). Returns None on failure."""
    claude_bin = find_claude_bin(cfg)
    if not claude_bin:
        return None
    try:
        log("Calling claude CLI (may take 1-2 minutes)...")
        proc = subprocess.run(
            [claude_bin, "-p", build_curate_prompt(cfg, candidates)],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        if proc.returncode != 0:
            log("claude CLI exited non-zero:", proc.stderr[:300])
            return None
        return parse_curate_response(proc.stdout.strip(), candidates, cfg)
    except subprocess.TimeoutExpired:
        log("claude CLI timed out")
        return None
    except Exception as e:
        log("claude CLI error:", e)
        return None


def curate(cfg, candidates):
    """AI curation: Anthropic API first (if ANTHROPIC_API_KEY is set), then the local CLI."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        result = curate_via_api(cfg, candidates)
        if result:
            return result
        log("API curation failed, trying local claude CLI...")
    return curate_via_cli(cfg, candidates)


KEYWORD_TAGS = [
    ("vision-language-action", "VLA"), ("vla", "VLA"),
    ("manipulat", "Manipulation"), ("grasp", "Grasping"),
    ("navigat", "Navigation"), ("humanoid", "Humanoids"),
    ("dexterous", "Dexterous Hands"), ("sim-to-real", "Sim2Real"),
    ("world model", "World Models"), ("locomot", "Locomotion"),
    ("reinforcement", "Reinforcement Learning"), ("embodied", DEFAULT_TAG),
]


def keyword_tag(text):
    low = text.lower()
    for kw, tag in KEYWORD_TAGS:
        if kw in low:
            return tag
    return DEFAULT_TAG


def item_digest(it):
    """Digest text of an item (accepts the legacy 'zh_summary' key from old latest.json files)."""
    return it.get("digest") or it.get("zh_summary") or ""


def build_items(cfg, candidates):
    curated = curate(cfg, candidates) if cfg.get("use_claude_cli", True) else None
    items = []
    if curated:
        for c in curated:
            items.append({
                "paper": candidates[c["idx"]],
                "tag": c["tag"],
                "tldr": c.get("tldr", ""),
                "position": c.get("position", ""),
                "digest": c["digest"],
                "highlights": c.get("highlights", []),
            })
    else:
        log("WARNING: AI curation unavailable (no ANTHROPIC_API_KEY and no working claude CLI); "
            "falling back to keyword tags + raw abstracts")
        for p in candidates[: cfg["top_n"]]:
            items.append({
                "paper": p,
                "tag": keyword_tag(p["title"] + " " + p["summary"]),
                "tldr": "",
                "position": "",
                "digest": "(AI digest unavailable) " + p["summary"][:400],
                "highlights": [],
            })
    for it in items:
        p = it["paper"]
        it["code"] = p.get("github") or pwc_code(p["id"]) or NO_CODE
    return items


# ---------------- Output: Markdown / Bark / macOS ----------------

def render_markdown(items, date_str):
    lines = ["# Embodied AI Daily Top %d · %s\n" % (len(items), date_str),
             "> New Embodied AI papers from arXiv, selected and explained by AI.\n"]
    for i, it in enumerate(items, 1):
        p = it["paper"]
        lines.append("## %d. [%s] %s" % (i, it["tag"], p["title"]))
        if it.get("tldr"):
            lines.append("\n> 💡 %s\n" % it["tldr"])
        if p.get("authors"):
            lines.append("**Authors**: " + ", ".join(p["authors"][:6]) +
                         (" et al." if len(p["authors"]) > 6 else ""))
        if it.get("position"):
            lines.append("\n**🧭 Position**: " + it["position"])
        lines.append("\n" + item_digest(it) + "\n")
        if it.get("highlights"):
            lines.append("**Highlights**:")
            for h in it["highlights"]:
                lines.append("- " + h)
            lines.append("")
        lines.append("**Links**:")
        lines.append("- 📄 arXiv: %s" % p["abs_url"])
        lines.append("- 📕 PDF: %s" % (p.get("pdf_url") or "—"))
        lines.append("- 💻 Code: %s" % it.get("code", NO_CODE))
        lines.append("")
    return "\n".join(lines)


def _truncate(s, limit=3200):
    """Truncate to `limit` UTF-8 bytes (Bark payload limit)."""
    if len(s.encode("utf-8")) <= limit:
        return s
    out = s
    while len(out.encode("utf-8")) > limit - 3:
        out = out[:-1]
    return out + "…"


def push_bark(cfg, title, body):
    key = cfg.get("bark_key", "").strip()
    if not key:
        log("bark_key not set, skipping iPhone push")
        return
    url = cfg["bark_server"].rstrip("/") + "/" + key
    payload = json.dumps({
        "title": title, "body": _truncate(body), "group": "Embodied Daily", "sound": "birdsong"
    }, ensure_ascii=False)
    # System curl is more reliable than urllib against Bark's TLS setup.
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "25", "-X", "POST", url,
             "-H", "Content-Type: application/json; charset=utf-8",
             "-d", payload],
            capture_output=True, text=True, timeout=30,
        )
        log("Bark push:", (proc.stdout.strip() or proc.stderr.strip())[:200])
    except Exception as e:
        log("Bark push failed:", e)


def _as_applescript_str(s):
    # AppleScript string literal: escape backslashes and double quotes, drop newlines.
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", " ").replace("\n", " ")
    return '"' + s + '"'


def notify_macos(title, subtitle, msg):
    if not IS_MACOS:
        return
    try:
        script = "display notification %s with title %s subtitle %s" % (
            _as_applescript_str(msg), _as_applescript_str(title), _as_applescript_str(subtitle))
        subprocess.run(["osascript", "-e", script], timeout=15)
    except Exception as e:
        log("macOS notification failed:", e)


# ---------------- Email (HTML attachment) ----------------

def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s):
    s = _esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    return s


def simple_md_to_html(md_text):
    """Minimal Markdown -> HTML (headings, bold, links, lists, quotes); no third-party deps."""
    html = ['<html><head><meta charset="utf-8"><style>',
            'body{font-family:-apple-system,"Segoe UI",sans-serif;margin:2em;line-height:1.6}',
            'h1{color:#333;border-bottom:2px solid #ddd;padding-bottom:0.3em}',
            'h2{color:#555;margin-top:1.5em}',
            'a{color:#0066cc}',
            'blockquote{border-left:3px solid #ccc;padding-left:1em;color:#666}',
            '</style></head><body>']
    for line in md_text.split("\n"):
        if line.startswith("# "):
            html.append("<h1>%s</h1>" % _esc(line[2:]))
        elif line.startswith("## "):
            html.append("<h2>%s</h2>" % _esc(line[3:]))
        elif line.startswith("> "):
            html.append("<blockquote>%s</blockquote>" % _inline(line[2:]))
        elif line.startswith("- "):
            html.append("<li>%s</li>" % _inline(line[2:]))
        elif line.strip() == "":
            html.append("<br>")
        else:
            html.append("<p>%s</p>" % _inline(line))
    html.append("</body></html>")
    return "\n".join(html)


def send_email(cfg, md_path, date_str, subject_prefix="📚 Embodied AI Daily"):
    """Send the digest as an HTML attachment over SMTP (no-op unless email_to is set)."""
    email_to = cfg.get("email_to", "").strip()
    if not email_to:
        return
    email_from = cfg.get("email_from", "").strip()
    smtp_host = cfg.get("smtp_host", "").strip()
    smtp_password = cfg.get("smtp_password", "").strip()
    if not all([email_from, smtp_host, smtp_password]):
        log("Incomplete email config (need email_from, smtp_host, smtp_password), skipping email")
        return

    att_path = md_path
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            html = simple_md_to_html(f.read())
        att_path = os.path.splitext(md_path)[0] + ".html"
        with open(att_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        log("HTML generation failed, attaching raw Markdown:", e)

    msg = email.mime.multipart.MIMEMultipart()
    msg["Subject"] = "%s · %s" % (subject_prefix, date_str)
    msg["From"] = email_from
    recipients = [e.strip() for e in email_to.split(",") if e.strip()]
    msg["To"] = ", ".join(recipients)
    msg.attach(email.mime.text.MIMEText(
        "Your Embodied AI paper digest is attached.\n\nDate: %s" % date_str, "plain", "utf-8"))
    att_name = os.path.basename(att_path)
    with open(att_path, "rb") as f:
        att = email.mime.application.MIMEApplication(f.read(), Name=att_name)
    att["Content-Disposition"] = 'attachment; filename="%s"' % att_name
    msg.attach(att)

    smtp_port = int(cfg.get("smtp_port", 465))
    try:
        ctx = ssl.create_default_context()
        if cfg.get("smtp_use_ssl", True):
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls(context=ctx)
        with server:
            server.login(email_from, smtp_password)
            server.sendmail(email_from, recipients, msg.as_string())
        log("Email sent: %s -> %d recipient(s)" % (att_name, len(recipients)))
    except Exception as e:
        log("Email failed:", e)


def push_digest(cfg, items, date_str):
    """Push one Bark notification per paper, each with its full digest."""
    if not cfg.get("bark_key", "").strip():
        log("bark_key not set, skipping iPhone push")
        return
    n = len(items)
    for i, it in enumerate(items, 1):
        p = it["paper"]
        lines = ["[%s] %s" % (it["tag"], p["title"])]
        if it.get("tldr"):
            lines.append("💡 " + it["tldr"])
        lines += ["", item_digest(it)]
        if it.get("highlights"):
            lines += ["", "✨ Highlights:"] + ["· " + h for h in it["highlights"]]
        lines += ["", "📄 arXiv: " + p["abs_url"], "💻 Code: " + it.get("code", NO_CODE)]
        push_bark(cfg, "📚 %d/%d Embodied AI Daily · %s" % (i, n, date_str), "\n".join(lines))


def prioritize(items, prio):
    """Stable-move items whose tag contains `prio` to the front."""
    if not prio:
        return list(items)
    return ([it for it in items if prio in it.get("tag", "")] +
            [it for it in items if prio not in it.get("tag", "")])


# ---------------- Weekend recap ----------------

# Archive heading: "## 1. [Tag] Title".
_HEADING_RE = re.compile(r"\[(.+?)\]\s*(.+?)$")
# Digest paragraph: the single line right before the highlights / links section.
_DIGEST_RE = re.compile(r"\n\n([^\n]+)\n\n\*\*(?:Highlights|Links)")


def parse_archive_md(text):
    """Recover items (id, title, tag, tldr, digest) from an archived Markdown digest."""
    items = []
    for block in re.split(r"^## \d+\.", text, flags=re.MULTILINE)[1:]:
        first = block.strip().split("\n")[0]
        hm = _HEADING_RE.search(first)
        tag = hm.group(1) if hm else DEFAULT_TAG
        title = hm.group(2).strip() if hm else first.strip()
        aid_m = re.search(ARXIV_ID_RE, block)
        if not aid_m:
            continue
        aid = aid_m.group(1)
        tldr_m = re.search(r"💡\s*(.+)", block)
        digest_m = _DIGEST_RE.search(block)
        items.append({
            "paper": {
                "id": aid, "title": title,
                "abs_url": "https://arxiv.org/abs/" + aid,
                "pdf_url": "https://arxiv.org/pdf/" + aid,
                "authors": [], "summary": "", "published": "", "github": "",
            },
            "tag": tag,
            "tldr": tldr_m.group(1).strip() if tldr_m else "",
            "position": "",
            "digest": (digest_m.group(1).strip() if digest_m else "")
            or "(Recovered from archive; see the paper for details.)",
            "highlights": [],
            "code": NO_CODE,
        })
    return items


def _load_archive_items(date_s):
    """Items for one archived day: prefer the structured .json, fall back to the .md."""
    json_path = os.path.join(ARCHIVE_DIR, date_s + ".json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f).get("items", [])
        except Exception:
            pass
    md_path = os.path.join(ARCHIVE_DIR, date_s + ".md")
    if os.path.exists(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                return parse_archive_md(f.read())
        except Exception:
            pass
    return []


def weekend_digest(cfg, deliver_outputs=True):
    """Weekend mode: arXiv does not announce on weekends, so push this week's unpushed papers."""
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    week_dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    log("Weekend mode: recapping archives %s ~ %s" % (week_dates[0], week_dates[-1]))

    push_n = int(cfg.get("push_n", 5))
    pushed_ids, all_items, seen = set(), [], set()
    for d in week_dates:
        day_items = _load_archive_items(d)
        # The first push_n papers of each weekday were already pushed to the phone.
        pushed_ids.update(it.get("paper", {}).get("id", "") for it in day_items[:push_n])
        for it in day_items:
            pid = it.get("paper", {}).get("id", "")
            if pid and pid not in seen:
                seen.add(pid)
                all_items.append(it)
    log("Already pushed this week:", len(pushed_ids), "| archived this week:", len(all_items))

    if not all_items:
        if deliver_outputs:
            push_bark(cfg, "📚 Weekend Embodied AI Recap", "No archived papers this week.")
        log("Nothing archived, exiting")
        return
    remaining = [it for it in all_items if it.get("paper", {}).get("id", "") not in pushed_ids]
    if not remaining:
        if deliver_outputs:
            push_bark(cfg, "📚 Weekend Embodied AI Recap",
                      "Every paper from this week has already been pushed.")
        log("Everything already pushed, exiting")
        return

    remaining = prioritize(remaining, str(cfg.get("push_priority", "")).strip())
    selected = remaining[: min(push_n, len(remaining))]
    date_str = today.strftime("%Y-%m-%d")
    label = date_str + " (weekend recap)"
    log("Weekend recap: %d papers" % len(selected))

    md = render_markdown(selected, label)
    md_path = os.path.join(ARCHIVE_DIR, date_str + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(HERE, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    log("Weekend recap archived:", md_path)

    if not deliver_outputs:
        return
    push_digest(cfg, selected, label)
    titles = "  ".join("%d.%s" % (i, it["paper"]["title"][:24]) for i, it in enumerate(selected, 1))
    notify_macos("📚 Weekend Embodied AI Recap · %s" % date_str,
                 " / ".join(dict.fromkeys(it["tag"] for it in selected)), titles)
    send_email(cfg, md_path, label, "📚 Weekend Embodied AI Recap")


# ---------------- Main ----------------

def deliver(cfg, items, date_str):
    """Phone gets the first push_n papers; Mac notification + digest show all top_n."""
    push_n = min(int(cfg.get("push_n", 5)), len(items))
    prio = str(cfg.get("push_priority", "")).strip()
    phone_items = prioritize(items, prio)
    if prio:
        log("Phone priority '%s': %d match(es)"
            % (prio, sum(prio in it.get("tag", "") for it in items)))
    push_digest(cfg, phone_items[:push_n], date_str)
    titles = "  ".join("%d.%s" % (i, it["paper"]["title"][:24]) for i, it in enumerate(items, 1))
    notify_macos("📚 Embodied AI Daily Top %d · %s (top %d pushed to phone)"
                 % (len(items), date_str, push_n),
                 " / ".join(dict.fromkeys(it["tag"] for it in items)), titles)
    # macOS notifications have no click action, so open the digest directly.
    if cfg.get("open_digest", True) and IS_MACOS:
        try:
            subprocess.run(["open", os.path.join(HERE, "latest.md")], timeout=15)
        except Exception as e:
            log("Failed to open digest:", e)
    send_email(cfg, os.path.join(HERE, "latest.md"), date_str)


def run(cfg, deliver_outputs=True):
    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    if datetime.now().weekday() >= 5:
        log("Weekend: arXiv has no new announcements, switching to weekend recap")
        weekend_digest(cfg, deliver_outputs)
        return

    log("Fetching candidates...")
    candidates = gather_candidates(cfg)
    log("Candidates:", len(candidates))
    if not candidates:
        if deliver_outputs:
            push_bark(cfg, "📚 Embodied AI Daily", "No papers fetched today (arXiv may not have updated).")
        log("No candidates, exiting")
        return
    items = build_items(cfg, candidates)
    log("Selected:", len(items))

    md = render_markdown(items, date_str)
    md_path = os.path.join(ARCHIVE_DIR, date_str + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    data = {"date": date_str, "items": items}
    # archive/<date>.json lets the weekend recap read structured data.
    with open(os.path.join(ARCHIVE_DIR, date_str + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # latest.md / latest.json are reused by --push-only.
    with open(os.path.join(HERE, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(HERE, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("Archived:", md_path)

    if deliver_outputs:
        deliver(cfg, items, date_str)
    log("Done")


def push_only(cfg):
    """Re-deliver the last run from latest.json without fetching or calling Claude."""
    path = os.path.join(HERE, "latest.json")
    if not os.path.exists(path):
        log("latest.json not found; run once normally first")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    log("Re-pushing from latest.json, papers:", len(items))
    deliver(cfg, items, data.get("date", datetime.now().strftime("%Y-%m-%d")))
    log("Done")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Daily digest of new Embodied AI papers from arXiv.")
    ap.add_argument("--push-only", action="store_true",
                    help="re-deliver the last digest from latest.json without fetching")
    ap.add_argument("--no-deliver", action="store_true",
                    help="fetch, curate and archive only; no push, notification, email or open")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.push_only:
        push_only(cfg)
    else:
        run(cfg, deliver_outputs=not args.no_deliver)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("Fatal error:", repr(e))
        sys.exit(1)
