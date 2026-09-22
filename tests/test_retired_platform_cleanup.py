from __future__ import annotations

from pathlib import Path
import subprocess
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
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0:
            relative_paths = [
                Path(item.decode("utf-8", errors="replace"))
                for item in proc.stdout.split(b"\\0")
                if item
            ]
        else:
            # Fallback for source archives without .git metadata.  Ignore local
            # dependency/cache trees because this test is about repository code.
            ignored = {".git", "__pycache__", "node_modules", "tmp", ".venv", "venv"}
            relative_paths = [
                path.relative_to(ROOT)
                for path in ROOT.rglob("*")
                if path.is_file() and not any(part in ignored for part in path.parts)
            ]

        for relative in relative_paths:
            path = ROOT / relative
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if RETIRED_CODE in text.lower() or RETIRED_CN in text:
                hits.append(relative.as_posix())
        self.assertEqual(hits, [], "retired platform references remain: " + " | ".join(hits))


if __name__ == "__main__":
    unittest.main()
