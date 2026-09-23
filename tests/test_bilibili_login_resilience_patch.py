from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_login_resilience as patch


CORE_SOURCE = '''import asyncio
from playwright._impl._errors import TargetClosedError
from tools import utils
import config

async def start(self):
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[BilibiliCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[BilibiliCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(chromium, None, self.user_agent, headless=config.HEADLESS)
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # Create a client to interact with the xiaohongshu website.
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

            crawler_type_var.set(config.CRAWLER_TYPE)

async def launch_browser(self, chromium, playwright_proxy, user_agent, headless=True):
        if config.SAVE_LOGIN_STATE:
            user_data_dir = "bili_user_data_dir"
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
                channel="chrome",  # Use system's stable Chrome version
            )
            return browser_context
'''

LOGIN_SOURCE = '''import asyncio
import functools
import sys

from tenacity import RetryError
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
            utils.logger.info("[BilibiliLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
            sys.exit()

        # show login qrcode
        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)

        utils.logger.info(f"[BilibiliLogin.login_by_qrcode] Waiting for scan code login, remaining time is 20s")
        try:
            await self.check_login_state()
        except RetryError:
            utils.logger.info("[BilibiliLogin.login_by_qrcode] Login bilibili failed by qrcode login method ...")
            sys.exit()

        wait_redirect_seconds = 5
        await asyncio.sleep(wait_redirect_seconds)
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
            self.assertTrue(result["standard_browser_mode"])
            self.assertTrue(result["persistent_launch_retry"])
            self.assertTrue(result["bounded_home_navigation"])
            self.assertIn("BILIBILI_LOGIN_REQUIRED", first_login)
            self.assertIn("candidate.click(timeout=8000)", first_login)
            self.assertIn("CDP bootstrap skipped for Bilibili", first_core)
            self.assertIn("for _bili_launch_attempt in range(2):", first_core)
            self.assertIn('wait_until="domcontentloaded"', first_core)
            self.assertIn("[BILIBILI_HOME_NAVIGATION_DEGRADED]", first_core)
            self.assertIn("PROMOTION_WEEK_BILI_LOGIN_BOOTSTRAP", first_core)
            self.assertIn("[BILIBILI_SESSION_BOOTSTRAP_OK]", first_core)
            self.assertIn("BILIBILI_LOGIN_MANUAL_WAIT_V1", first_login)
            self.assertIn("[BILIBILI_LOGIN_WAIT]", first_login)
            self.assertIn("[BILIBILI_LOGIN_VERIFIED]", first_login)
            self.assertNotIn("login failed , have not found qrcode please check", first_login)


if __name__ == "__main__":
    unittest.main()
