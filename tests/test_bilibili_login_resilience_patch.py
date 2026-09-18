from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_login_resilience as patch


CORE_SOURCE = '''import asyncio
from tools import utils
import config

async def start(self):
            if not await self.bili_client.pong():
                login_obj = BilibiliLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.bili_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )
'''

LOGIN_SOURCE = '''import asyncio
from tools import utils

async def login_by_qrcode(self):
        # click login button
        login_button_ele = self.context_page.locator(
            "xpath=//div[@class='right-entry__outside go-login-btn']//div"
        )
        await login_button_ele.click()
        await asyncio.sleep(1)
        # find login qrcode
        qrcode_img_selector = "//div[@class='login-scan-box']//img"
        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
        if not base64_qrcode_img:
            return
'''


class BilibiliLoginResiliencePatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_syntax_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "media_platform/bilibili").mkdir(parents=True)
            core = root / "media_platform/bilibili/core.py"
            login = root / "media_platform/bilibili/login.py"
            core.write_text(CORE_SOURCE, encoding="utf-8")
            login.write_text(LOGIN_SOURCE, encoding="utf-8")

            patch.patch_core(root)
            patch.patch_login(root)
            first_core = core.read_text(encoding="utf-8")
            first_login = login.read_text(encoding="utf-8")

            patch.patch_core(root)
            patch.patch_login(root)
            self.assertEqual(first_core, core.read_text(encoding="utf-8"))
            self.assertEqual(first_login, login.read_text(encoding="utf-8"))

            ast.parse(first_core)
            ast.parse(first_login)
            result = patch.check(root)
            self.assertTrue(result["ok"])
            self.assertTrue(result["existing_qr_detection"])
            self.assertTrue(result["session_probe_retry"])
            self.assertIn("BILIBILI_LOGIN_REQUIRED", first_login)
            self.assertIn("candidate.click(timeout=8000)", first_login)


if __name__ == "__main__":
    unittest.main()
