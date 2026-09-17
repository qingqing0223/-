from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.patch_kuaishou_login_resilience import check, patch_core, patch_login


CORE = '''import asyncio\n\nclass Dummy:\n    async def start(self):\n        self.ks_client = await self.create_ks_client(None)\n        if True:\n            if not await self.ks_client.pong():\n                login_obj = KuaishouLogin(\n                    login_type=config.LOGIN_TYPE,\n                    login_phone=httpx_proxy_format,\n                    browser_context=self.browser_context,\n                    context_page=self.context_page,\n                    cookie_str=config.COOKIES,\n                )\n                await login_obj.begin()\n                await self.ks_client.update_cookies(\n                    browser_context=self.browser_context,\n                    urls=self.cookie_urls,\n                )\n'''

LOGIN = '''import asyncio\n\nclass Dummy:\n    async def login_by_qrcode(self):\n        # click login button\n        login_button_ele = self.context_page.locator(\n            "xpath=//p[text()='登录']"\n        )\n        await login_button_ele.click()\n'''


class KuaishouLoginResiliencePatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_adds_bounded_official_login_flow(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "media_platform" / "kuaishou"
            base.mkdir(parents=True)
            core = base / "core.py"
            login = base / "login.py"
            core.write_text(CORE, encoding="utf-8")
            login.write_text(LOGIN, encoding="utf-8")

            patch_core(root)
            patch_login(root)
            first_core = core.read_text(encoding="utf-8")
            first_login = login.read_text(encoding="utf-8")
            status = check(root)

            self.assertTrue(status["ok"], status)
            self.assertIn("for _ks_pong_attempt in range(3):", first_core)
            self.assertIn("KUAISHOU_LOGIN_REQUIRED", first_core)
            self.assertIn("button:has-text('登录')", first_login)
            self.assertIn("candidate.click(timeout=8000)", first_login)
            self.assertIn("KUAISHOU_LOGIN_REQUIRED", first_login)

            patch_core(root)
            patch_login(root)
            self.assertEqual(first_core, core.read_text(encoding="utf-8"))
            self.assertEqual(first_login, login.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
