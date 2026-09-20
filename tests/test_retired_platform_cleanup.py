from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RETIRED_CODE = "tie" + "ba"
RETIRED_CN = "百度" + "贴吧"
TEXT_SUFFIXES = {
    ".py", ".ps1", ".json", ".md", ".txt", ".yml", ".yaml",
    ".html", ".js", ".css", ".toml", ".csv",
}


class RetiredPlatformCleanupTests(unittest.TestCase):
    def test_retired_platform_has_no_tracked_text_references(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if RETIRED_CODE in text.lower() or RETIRED_CN in text:
                hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [], "retired platform references remain: " + " | ".join(hits))


if __name__ == "__main__":
    unittest.main()
