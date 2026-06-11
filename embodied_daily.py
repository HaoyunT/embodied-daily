#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日具身智能(Embodied AI)论文日报
- 从 arXiv 抓取最近的具身相关论文
- 调用本机 claude CLI 做中文摘要 / 方向标签 / Top5 排序 (复用 Claude 订阅, 无需 API key)
- 抽取代码仓库链接 (摘要中的 GitHub / Papers with Code 兜底)
- 推送到 iPhone(Bark) + macOS 通知, 并存档为 Markdown

依赖: 仅 Python 标准库 + 系统 curl。可选 claude CLI。
配置: 同目录 config.json
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
    "bark_key": "",                       # 必填: Bark App 里那串 key, 例如 https://api.day.app/XXXXXX 的 XXXXXX
    "bark_server": "https://api.day.app", # 自建 Bark 服务器可改
    "top_n": 10,                          # 精选篇数(Mac 日报/存档展示全部 top_n 篇)
    "push_n": 5,                          # iPhone 只推送前 push_n 篇 (<= top_n)
    "interests": "",                      # 个人兴趣偏好, 相关论文优先选入并排前面
    "same_day_only": True,                # True: 只推当日(最新一个公布日)的论文, 不跨多天
    "lookback_days": 3,                   # same_day_only=False 时生效: 回看最近几天
    "max_candidates": 40,                 # 送给 claude 排序的候选上限
    "queries": [
        "cat:cs.RO",
        "all:embodied",
        "all:%22vision-language-action%22",
        "all:%22robot+manipulation%22"
    ],
    "use_claude_cli": True,               # 用 claude(API优先, 否则CLI)做中文摘要; false 则只给英文摘要
    "api_model": "claude-sonnet-4-6",     # 云端用 Anthropic API 时的模型 (可被环境变量 ANTHROPIC_MODEL 覆盖)
    "claude_bin": "",                     # 留空自动探测; 也可写绝对路径如 /Users/xxx/.local/bin/claude
    "open_digest": True                   # 跑完后自动用默认程序打开当天日报 latest.md (Mac)
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
            log("config.json 解析失败, 用默认值:", e)
    # 环境变量覆盖 (云端/CI 没有 config.json 时用)
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


# ---------------- arXiv 抓取 ----------------

def fetch_query(query, max_results):
    url = (
        "https://export.arxiv.org/api/query?search_query=" + query +
        "&sortBy=submittedDate&sortOrder=descending&max_results=" + str(max_results)
    )
    try:
        return http_get(url)
    except Exception as e:
        log("arXiv 查询失败:", query, e)
        return ""


def parse_atom(xml_text):
    out = []
    if not xml_text.strip():
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        log("XML 解析失败:", e)
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
        # 限定当日: 只保留最新一个公布日的论文, 不跨多天 (即使不足 top_n 也不向前补)
        dates = [p["published"][:10] for p in cand if p.get("published")]
        if dates:
            newest = max(dates)
            pool = [p for p in cand if p.get("published", "")[:10] == newest]
            log("当日批次:", newest, "篇数:", len(pool))
        else:
            pool = cand
    else:
        # 回看 lookback 天; 不够 top_n 再用更早的补齐
        recent = [p for p in cand if recent_enough(p["published"], cfg["lookback_days"])]
        pool = recent if len(recent) >= cfg["top_n"] else cand
    return pool[: cfg["max_candidates"]]


# ---------------- Papers with Code 兜底找代码 ----------------

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


# ---------------- claude CLI 中文摘要/标签/排序 ----------------

def find_claude_bin(cfg):
    if cfg.get("claude_bin"):
        return cfg["claude_bin"]
    for p in [os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if os.path.exists(p):
            return p
    # PATH 探测
    try:
        out = subprocess.run(["which", "claude"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def build_curate_prompt(cfg, candidates):
    """构造精选+解读 prompt (PaperLocus 风格: 文献定位 + 断言/推断区分)"""
    listing = []
    for i, p in enumerate(candidates):
        abs = p["summary"][:1100]
        listing.append("[%d] 标题: %s\n摘要: %s" % (i, p["title"], abs))
    interests = str(cfg.get("interests", "")).strip()
    interest_line = ""
    if interests:
        interest_line = (
            "【读者偏好】我个人重点关注: %s。与这些方向相关的论文请优先选入、"
            "并排在更靠前的位置; 但若当天有明显更重要的其他具身工作, 仍可纳入。\n" % interests
        )
    head = (
        "你是具身智能(Embodied AI)方向的资深科研助理, 擅长把论文放进文献脉络里解读(参考 PaperLocus 的读法)。\n"
        "下面是若干篇 arXiv 论文候选(仅含标题+摘要)。\n"
        "请从中挑选与【具身智能】最相关、最有价值的 %d 篇(涵盖如 VLA、机器人操作/抓取、"
        "导航、人形机器人、灵巧手、sim-to-real、世界模型、强化学习控制 等)。\n" % cfg["top_n"]
    )
    body = (
        "对每篇产出结构化中文解读, 包含以下字段:\n"
        "- tag: 简短中文方向标签(如 VLA / 灵巧手 / 世界模型)\n"
        "- tldr: 一句话亮点(20-30字, 让人一眼知道这篇牛在哪)\n"
        "- position: 文献定位(1-2句), 用\"在A基础上改了B, 从而得到C\"的框架, "
        "并点明它主要在和哪类先前工作/baseline 对比、属于哪条研究脉络\n"
        "- zh_summary: 详细解读(5-8句), 依次讲清楚: ①研究要解决的问题/痛点 "
        "②方法/核心思路 ③主要创新点 ④实验设计与关键结果(有数字就写) ⑤价值与适用范围/局限。"
        "只依据摘要可得的信息, 不要编造数据、baseline、代码或未提及的结论; "
        "若是推断而非论文明确断言, 用\"推测/可能\"标注。\n"
        "- highlights: 2-4 条要点(数组, 每条不超过25字, 提炼关键贡献或数字结果)\n"
        "语言通俗准确, 面向有AI基础的读者, 不堆砌英文术语。\n"
        "严格只输出一个 JSON 数组, 不要任何额外文字、不要 markdown 代码块。\n"
        "格式: [{\"idx\": 候选编号(整数), \"tag\": \"...\", \"tldr\": \"...\", "
        "\"position\": \"...\", \"zh_summary\": \"...\", \"highlights\": [\"...\", \"...\"]}]\n"
        "按重要性从高到低排序, 恰好 %d 个元素。\n\n候选列表:\n%s"
        % (cfg["top_n"], "\n\n".join(listing))
    )
    return head + interest_line + body


def parse_curate_response(raw, candidates, cfg):
    """从模型原始输出里抽取 JSON 数组并清洗"""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        log("模型输出未找到 JSON 数组")
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
                "tag": str(item.get("tag", "具身智能")).strip(),
                "tldr": str(item.get("tldr", "")).strip(),
                "position": str(item.get("position", "")).strip(),
                "zh_summary": str(item.get("zh_summary", "")).strip(),
                "highlights": [str(x).strip() for x in hl if str(x).strip()],
            })
    return cleaned[: cfg["top_n"]] or None


def curate_via_api(cfg, candidates):
    """用 Anthropic API 做精选+解读 (云端/无 claude CLI 时), 失败返回 None"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("ANTHROPIC_MODEL", cfg.get("api_model", "claude-sonnet-4-6"))
    prompt = build_curate_prompt(cfg, candidates)
    payload = json.dumps({
        "model": model,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        log("调用 Anthropic API 生成中文摘要 (模型 %s)..." % model)
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        raw = "".join(b.get("text", "") for b in data.get("content", []))
        return parse_curate_response(raw, candidates, cfg)
    except Exception as e:
        log("Anthropic API 调用失败:", e)
        return None


def curate_via_cli(cfg, candidates):
    """用本机 claude CLI 做精选+解读 (复用 Claude 订阅), 失败返回 None"""
    claude_bin = find_claude_bin(cfg)
    if not claude_bin:
        return None
    prompt = build_curate_prompt(cfg, candidates)
    try:
        log("调用 claude CLI 生成中文摘要 (可能需要 1-2 分钟)...")
        proc = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        if proc.returncode != 0:
            log("claude CLI 返回非零:", proc.stderr[:300])
            return None
        return parse_curate_response(proc.stdout.strip(), candidates, cfg)
    except subprocess.TimeoutExpired:
        log("claude CLI 超时")
        return None
    except Exception as e:
        log("claude CLI 调用异常:", e)
        return None


def curate(cfg, candidates):
    """智能精选+解读: 优先 Anthropic API(云端), 否则本机 claude CLI; 都不行返回 None"""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        result = curate_via_api(cfg, candidates)
        if result:
            return result
        log("API 方式失败, 尝试本机 claude CLI...")
    return curate_via_cli(cfg, candidates)


KEYWORD_TAGS = [
    ("vision-language-action", "VLA"), ("vla", "VLA"),
    ("manipulat", "机器人操作"), ("grasp", "抓取"),
    ("navigat", "导航"), ("humanoid", "人形机器人"),
    ("dexterous", "灵巧手"), ("sim-to-real", "Sim2Real"),
    ("world model", "世界模型"), ("locomot", "运动控制"),
    ("reinforcement", "强化学习"), ("embodied", "具身智能"),
]


def keyword_tag(text):
    low = text.lower()
    for kw, tag in KEYWORD_TAGS:
        if kw in low:
            return tag
    return "具身智能"


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
        log("使用关键词兜底模式 (英文摘要)")
        for p in candidates[: cfg["top_n"]]:
            items.append({
                "paper": p,
                "tag": keyword_tag(p["title"] + " " + p["summary"]),
                "tldr": "",
                "position": "",
                "zh_summary": "(未启用智能摘要) " + p["summary"][:400],
                "highlights": [],
            })
    # 补全代码链接
    for it in items:
        p = it["paper"]
        code = p.get("github") or pwc_code(p["id"]) or "暂无"
        it["code"] = code
    return items


# ---------------- 输出: Markdown / Bark / macOS ----------------

def render_markdown(items, date_str):
    lines = ["# 今日具身智能 Top%d · %s\n" % (len(items), date_str),
             "> 每日自动抓取 arXiv 具身智能(Embodied AI)最新论文, AI 精选解读(PaperLocus 风格)。\n"]
    for i, it in enumerate(items, 1):
        p = it["paper"]
        lines.append("## %d. 【%s】%s" % (i, it["tag"], p["title"]))
        if it.get("tldr"):
            lines.append("\n> 💡 %s\n" % it["tldr"])
        if p.get("authors"):
            lines.append("**作者**: " + ", ".join(p["authors"][:6]) +
                         (" 等" if len(p["authors"]) > 6 else ""))
        if it.get("position"):
            lines.append("\n**🧭 文献定位**: " + it["position"])
        lines.append("\n" + it["zh_summary"] + "\n")
        if it.get("highlights"):
            lines.append("**亮点**:")
            for h in it["highlights"]:
                lines.append("- " + h)
            lines.append("")
        lines.append("**链接**:")
        lines.append("- 📄 arXiv: %s" % p["abs_url"])
        lines.append("- 📕 PDF: %s" % (p.get("pdf_url") or "—"))
        lines.append("- 💻 代码: %s" % it["code"])
        lines.append("")
    return "\n".join(lines)


def render_push_body(items):
    # 单条推送: 每篇含标签+标题+一句话亮点+关键要点+链接; 完整长篇解读见 Markdown 存档
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
    # 按字节安全截断
    out = s
    while len(out.encode("utf-8")) > limit - 3:
        out = out[:-1]
    return out + "…"


def push_bark(cfg, title, body):
    key = cfg.get("bark_key", "").strip()
    if not key:
        log("未配置 bark_key, 跳过 iPhone 推送 (请在 config.json 填入)")
        return
    url = cfg["bark_server"].rstrip("/") + "/" + key
    payload = json.dumps({
        "title": title, "body": _truncate(body), "group": "具身日报", "sound": "birdsong"
    }, ensure_ascii=False)
    # 用系统 curl 推送 (比 urllib 对 Bark 的 TLS 更稳定)
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "25", "-X", "POST", url,
             "-H", "Content-Type: application/json; charset=utf-8",
             "-d", payload],
            capture_output=True, text=True, timeout=30,
        )
        msg = proc.stdout.strip() or proc.stderr.strip()
        log("Bark 推送:", msg[:200])
    except Exception as e:
        log("Bark 推送失败:", e)


def _as_str(s):
    # AppleScript 字符串: 保留中文(不能用 \uXXXX), 转义反斜杠和双引号, 去掉换行
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", " ").replace("\n", " ")
    return '"' + s + '"'


def notify_macos(title, subtitle, msg):
    try:
        script = "display notification %s with title %s subtitle %s" % (
            _as_str(msg), _as_str(title), _as_str(subtitle))
        subprocess.run(["osascript", "-e", script], timeout=15)
    except Exception as e:
        log("macOS 通知失败:", e)


def push_digest(cfg, items, date_str):
    """每篇论文单独推一条完整详细解读 (共 N 条, 每条都在 Bark 上限内)"""
    if not cfg.get("bark_key", "").strip():
        log("未配置 bark_key, 跳过 iPhone 推送 (请在 config.json 填入)")
        return
    n = len(items)
    for i, it in enumerate(items, 1):
        p = it["paper"]
        title = "📚 %d/%d 今日具身 · %s" % (i, n, date_str)
        lines = ["【%s】%s" % (it["tag"], p["title"])]
        if it.get("tldr"):
            lines.append("💡 " + it["tldr"])
        lines.append("")
        lines.append(it["zh_summary"])
        if it.get("highlights"):
            lines.append("")
            lines.append("✨ 亮点:")
            for h in it["highlights"]:
                lines.append("· " + h)
        lines.append("")
        lines.append("📄 arXiv: " + p["abs_url"])
        lines.append("💻 代码: " + it["code"])
        push_bark(cfg, title, "\n".join(lines))


def main():
    cfg = load_config()
    date_str = datetime.now().strftime("%Y-%m-%d")
    log("开始抓取候选...")
    candidates = gather_candidates(cfg)
    log("候选数:", len(candidates))
    if not candidates:
        push_bark(cfg, "📚 今日具身智能", "今日未抓取到论文 (arXiv 可能无更新)")
        log("无候选, 退出")
        return
    items = build_items(cfg, candidates)
    log("最终篇数:", len(items))

    md = render_markdown(items, date_str)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    md_path = os.path.join(ARCHIVE_DIR, date_str + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    # 同时维护 latest.md 与结构化的 latest.json (供 --push-only 复用)
    with open(os.path.join(HERE, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(HERE, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "items": items}, f, ensure_ascii=False, indent=2)
    log("已存档:", md_path)

    deliver(cfg, items, date_str)
    log("完成")


def deliver(cfg, items, date_str):
    """推送/通知/打开: iPhone 只推前 push_n 篇, Mac 通知+打开含全部 top_n 篇的日报"""
    # iPhone: 只推前 push_n 篇 (默认5); Mac/存档: 全部 top_n 篇 (默认10)
    push_n = min(int(cfg.get("push_n", 5)), len(items))
    push_digest(cfg, items[:push_n], date_str)
    # Mac 桌面通知一条汇总 (列出全部 top_n 篇标题)
    titles = "  ".join("%d.%s" % (i, it["paper"]["title"][:24])
                       for i, it in enumerate(items, 1))
    notify_macos("📚 今日具身智能 Top%d · %s (手机推前%d篇)" % (len(items), date_str, push_n),
                 " / ".join(dict.fromkeys(it["tag"] for it in items)),
                 titles)
    # 自动用默认程序打开当天日报 (Mac 原生通知点击无动作, 用这个兜底)
    if cfg.get("open_digest", True):
        try:
            subprocess.run(["open", os.path.join(HERE, "latest.md")], timeout=15)
        except Exception as e:
            log("打开日报失败:", e)


def push_only():
    """读取上次生成的 latest.json 直接重推, 不重新抓取/调用 claude"""
    cfg = load_config()
    path = os.path.join(HERE, "latest.json")
    if not os.path.exists(path):
        log("没有 latest.json, 请先正常运行一次")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    log("从 latest.json 重推, 篇数:", len(items))
    deliver(cfg, items, date_str)
    log("完成")


if __name__ == "__main__":
    try:
        if "--push-only" in sys.argv:
            push_only()
        else:
            main()
    except Exception as e:
        log("致命错误:", repr(e))
        sys.exit(1)
