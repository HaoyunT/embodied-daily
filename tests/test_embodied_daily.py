"""Offline unit tests for embodied_daily (no network, no Claude, no push)."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import embodied_daily as ed  # noqa: E402

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2611.12345v1</id>
    <published>2026-11-25T17:59:59Z</published>
    <title>A Dexterous
      Hand Policy</title>
    <summary>We learn dexterous manipulation. Code: https://github.com/foo/bar.</summary>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2611.12345v1" rel="related"/>
  </entry>
</feed>
"""

LEGACY_MD = """# 今日具身智能 Top2 · 2026-11-24

> 每日自动抓取 arXiv 具身智能(Embodied AI)最新论文, AI 精选解读(PaperLocus 风格)。

## 1. 【灵巧手】Paper One
**作者**: A, B

旧格式的详细解读。

**亮点**:
- x

**链接**:
- 📄 arXiv: https://arxiv.org/abs/2611.00001
- 💻 代码: 暂无

## 2. 【导航】Paper Two

**链接**:
- 📄 arXiv: https://arxiv.org/abs/2611.00002
"""


def make_item(aid="2611.00003", tag="VLA", title="Paper Three"):
    return {
        "paper": {"id": aid, "title": title, "abs_url": "https://arxiv.org/abs/" + aid,
                  "pdf_url": "https://arxiv.org/pdf/" + aid, "authors": ["A"] * 7},
        "tag": tag, "tldr": "Short highlight.", "position": "Builds on X.",
        "digest": "Detailed digest.", "highlights": ["h1", "h2"], "code": "N/A",
    }


class ParseAtomTest(unittest.TestCase):
    def test_parses_entry(self):
        (p,) = ed.parse_atom(ATOM_SAMPLE)
        self.assertEqual(p["id"], "2611.12345")
        self.assertEqual(p["title"], "A Dexterous Hand Policy")
        self.assertEqual(p["authors"], ["Alice", "Bob"])
        self.assertEqual(p["abs_url"], "https://arxiv.org/abs/2611.12345")
        self.assertEqual(p["pdf_url"], "https://arxiv.org/pdf/2611.12345v1")
        self.assertEqual(p["github"], "https://github.com/foo/bar")

    def test_bad_input(self):
        self.assertEqual(ed.parse_atom(""), [])
        self.assertEqual(ed.parse_atom("<not xml"), [])


class CurateParseTest(unittest.TestCase):
    cfg = {"top_n": 2}
    cands = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

    def test_valid_json_with_noise(self):
        raw = 'Sure:\n[{"idx": 2, "tag": "VLA", "tldr": "t", "digest": "d", "highlights": "h"},' \
              ' {"idx": 9, "tag": "x"}, {"idx": 0, "tag": "Nav", "zh_summary": "legacy"}]'
        out = ed.parse_curate_response(raw, self.cands, self.cfg)
        self.assertEqual([o["idx"] for o in out], [2, 0])
        self.assertEqual(out[0]["highlights"], ["h"])
        self.assertEqual(out[1]["digest"], "legacy")

    def test_repairs_raw_newlines(self):
        raw = '[{"idx": 1, "tag": "VLA", "digest": "line one\nline two"}]'
        out = ed.parse_curate_response(raw, self.cands, self.cfg)
        self.assertEqual(out[0]["digest"], "line one line two")

    def test_garbage(self):
        self.assertIsNone(ed.parse_curate_response("no json here", self.cands, self.cfg))

    def test_prompt_mentions_language_and_interests(self):
        cfg = {"top_n": 3, "language": "Chinese", "interests": "VLA"}
        prompt = ed.build_curate_prompt(cfg, [{"title": "T", "summary": "S"}])
        self.assertIn("in Chinese", prompt)
        self.assertIn("Reader interests", prompt)
        self.assertIn("exactly 3 elements", prompt)


class RenderAndArchiveTest(unittest.TestCase):
    def test_keyword_tag(self):
        self.assertEqual(ed.keyword_tag("A Vision-Language-Action model"), "VLA")
        self.assertEqual(ed.keyword_tag("nothing relevant"), ed.DEFAULT_TAG)

    def test_render_roundtrip(self):
        md = ed.render_markdown([make_item()], "2026-11-27")
        self.assertIn("## 1. [VLA] Paper Three", md)
        self.assertIn("et al.", md)
        (it,) = ed.parse_archive_md(md)
        self.assertEqual(it["paper"]["id"], "2611.00003")
        self.assertEqual(it["tag"], "VLA")
        self.assertEqual(it["paper"]["title"], "Paper Three")
        self.assertEqual(it["tldr"], "Short highlight.")
        self.assertEqual(it["digest"], "Detailed digest.")

    def test_parse_legacy_archive(self):
        items = ed.parse_archive_md(LEGACY_MD)
        self.assertEqual([i["paper"]["id"] for i in items], ["2611.00001", "2611.00002"])
        self.assertEqual(items[0]["tag"], "灵巧手")
        self.assertEqual(items[0]["paper"]["title"], "Paper One")
        self.assertEqual(items[0]["digest"], "旧格式的详细解读。")

    def test_prioritize_is_stable(self):
        items = [make_item("1", "Nav"), make_item("2", "VLA"), make_item("3", "VLA-X")]
        ids = [i["paper"]["id"] for i in ed.prioritize(items, "VLA")]
        self.assertEqual(ids, ["2", "3", "1"])
        self.assertEqual(ed.prioritize(items, ""), items)

    def test_recent_pushed_ids(self):
        with tempfile.TemporaryDirectory() as d:
            for name, aid in [("2026-11-26.md", "2611.1"), ("2026-11-27.md", "2611.2"),
                              ("2026-11-01.md", "2611.3"), ("notes.md", "2611.4")]:
                with open(os.path.join(d, name), "w") as f:
                    f.write("https://arxiv.org/abs/%s\n" % aid)
            ids = ed.recent_pushed_ids(7, archive_dir=d, today=date(2026, 11, 27))
        self.assertEqual(ids, {"2611.1"})

    def test_truncate_bytes(self):
        s = "具" * 2000
        out = ed._truncate(s, 100)
        self.assertLessEqual(len(out.encode("utf-8")), 100)
        self.assertTrue(out.endswith("…"))

    def test_html(self):
        html = ed.simple_md_to_html("# T\n- **b** [x](http://y)\n")
        self.assertIn("<h1>T</h1>", html)
        self.assertIn('<li><b>b</b> <a href="http://y">x</a></li>', html)


class ConfigTest(unittest.TestCase):
    def test_example_config_matches_defaults(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "config.example.json")) as f:
            example = json.load(f)
        self.assertEqual(set(example), set(ed.DEFAULT_CONFIG))

    def test_env_override(self):
        os.environ["EMBODIED_LANGUAGE"] = "Chinese"
        try:
            cfg = ed.load_config(path="/nonexistent/config.json")
        finally:
            del os.environ["EMBODIED_LANGUAGE"]
        self.assertEqual(cfg["language"], "Chinese")


if __name__ == "__main__":
    unittest.main()
