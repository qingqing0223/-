from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.patch_kuaishou_startup_resilience import MARKER, patch_core, check


class KuaishouStartupPatchTests(unittest.TestCase):
    def test_duplicate_homepage_goto_only_patches_startup_window_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = root / "media_platform" / "kuaishou" / "core.py"
            core.parent.mkdir(parents=True, exist_ok=True)
            core.write_text(
                "import asyncio\n\n"
                "class Dummy:\n"
                "    async def start(self):\n"
                "        self.index_url = 'https://www.kuaishou.com'\n"
                "        self.context_page = object()\n"
                "        await self.context_page.add_init_script(KS_SIGN_CAPTURE_SCRIPT)\n"
                "        await self.context_page.goto(f\"{self.index_url}?isHome=1\")\n"
                "        # Create a client to interact with the kuaishou website.\n"
                "        self.ks_client = None\n\n"
                "    async def another_place(self):\n"
                "        await self.context_page.goto(f\"{self.index_url}?isHome=1\")\n",
                encoding="utf-8",
            )

            patch_core(root)
            first = core.read_text(encoding="utf-8")
            self.assertIn(MARKER, first)
            self.assertIn('wait_until="commit"', first)
            self.assertIn('wait_for_load_state("domcontentloaded", timeout=12000)', first)
            self.assertIn('"kuaishou.com" not in current_url', first)
            self.assertEqual(first.count('await self.context_page.goto(f"{self.index_url}?isHome=1")'), 1)
            self.assertTrue(check(root)["ok"])

            patch_core(root)
            second = core.read_text(encoding="utf-8")
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
