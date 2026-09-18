from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_LOGIN_RESILIENCE_V1"
STARTUP_MARKER = "PROMOTION_WEEK_BILI_BROWSER_STARTUP_V2"
NAVIGATION_MARKER = "PROMOTION_WEEK_BILI_HOME_NAVIGATION_V3"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_core(root: Path) -> None:
    path = root / "media_platform/bilibili/core.py"
    text = read(path)

    # Keep the validated V1 session-probe patch composable with later startup
    # hardening. Do not return early merely because V1 is already installed.
    if f"# {MARKER}: bounded session probe" not in text:
        old = '''            if not await self.bili_client.pong():
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
        new = f'''            # {MARKER}: bounded session probe before treating one transient
            # Bilibili API failure as a logged-out session.
            _bili_pong_ok = False
            for _bili_pong_attempt in range(3):
                try:
                    if await self.bili_client.pong():
                        _bili_pong_ok = True
                        break
                except Exception as _bili_pong_exc:
                    utils.logger.warning(
                        f"[BILIBILI_SESSION_PROBE] attempt={{_bili_pong_attempt + 1}} "
                        f"type={{type(_bili_pong_exc).__name__}}"
                    )
                if _bili_pong_attempt < 2:
                    await asyncio.sleep(2)

            if not _bili_pong_ok:
                utils.logger.warning(
                    "[BILIBILI_LOGIN_REQUIRED] login required after bounded session probes; "
                    "opening Bilibili's official login flow"
                )
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
        text = replace_once(text, old, new, "Bilibili bounded session probe")

    # Bilibili repeatedly returned HTTP 502 from Chrome's CDP /json/version
    # endpoint on the monitoring machine. The upstream fallback then tried to
    # launch a second persistent Chrome while the failed CDP Chrome was still
    # alive, which could exit immediately with TargetClosedError/0xC0000142.
    # For Bilibili only, use Playwright's standard persistent profile directly.
    if f"# {STARTUP_MARKER}: use standard persistent browser" not in text:
        old = '''            # Choose launch mode based on configuration
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
'''
        new = f'''            # {STARTUP_MARKER}: use standard persistent browser.
            # Bilibili's CDP bootstrap is intentionally skipped for this monitoring
            # deployment because repeated /json/version HTTP 502 failures left a
            # Chrome process alive and made the fallback browser unstable. This
            # does not bypass login or verification; it only selects Playwright's
            # normal persistent-context launch path.
            utils.logger.info(
                "[BILIBILI_BROWSER_STARTUP] using standard persistent browser mode; "
                "CDP bootstrap skipped for Bilibili"
            )
            chromium = playwright.chromium
            self.browser_context = await self.launch_browser(
                chromium,
                playwright_proxy_format,
                self.user_agent,
                headless=config.HEADLESS,
            )
            await self.browser_context.add_init_script(path="libs/stealth.min.js")
'''
        text = replace_once(text, old, new, "Bilibili browser startup mode")

    # A fully loaded Bilibili homepage is not required when the persistent
    # profile already contains a valid session. Detail subprocesses were failing
    # before API-client creation because page.goto(..., wait_until="load") timed
    # out on slow third-party resources. Use a short DOMContentLoaded probe and
    # tolerate only navigation timeouts; the following pong() still determines
    # whether the cached session is actually usable.
    if f"# {NAVIGATION_MARKER}: bounded homepage navigation" not in text:
        old = '''            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # Create a client to interact with the xiaohongshu website.
'''
        new = f'''            self.context_page = await self.browser_context.new_page()

            # {NAVIGATION_MARKER}: bounded homepage navigation.
            _bili_home_ready = False
            for _bili_home_attempt in range(2):
                try:
                    await self.context_page.goto(
                        self.index_url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    _bili_home_ready = True
                    break
                except Exception as _bili_home_exc:
                    if type(_bili_home_exc).__name__ != "TimeoutError":
                        raise
                    utils.logger.warning(
                        f"[BILIBILI_HOME_NAVIGATION] attempt={{_bili_home_attempt + 1}} "
                        f"timed out; cached session/API probe will continue"
                    )
                    if _bili_home_attempt < 1:
                        await asyncio.sleep(1)

            if not _bili_home_ready:
                utils.logger.warning(
                    "[BILIBILI_HOME_NAVIGATION_DEGRADED] homepage did not reach "
                    "DOMContentLoaded within bounded retries; continuing to cached "
                    "session/API probe"
                )

            # Create a client to interact with the xiaohongshu website.
'''
        text = replace_once(text, old, new, "Bilibili bounded homepage navigation")

    # One bounded retry handles transient Chrome 0xC0000142 / TargetClosedError
    # without changing the persistent profile that stores the official login.
    if f"# {STARTUP_MARKER}: bounded persistent-context retry" not in text:
        old = '''            browser_context = await chromium.launch_persistent_context(
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
        new = f'''            # {STARTUP_MARKER}: bounded persistent-context retry.
            _bili_launch_exc = None
            for _bili_launch_attempt in range(2):
                try:
                    browser_context = await chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        accept_downloads=True,
                        headless=headless,
                        proxy=playwright_proxy,  # type: ignore
                        viewport={{
                            "width": 1920,
                            "height": 1080
                        }},
                        user_agent=user_agent,
                        channel="chrome",  # Use system's stable Chrome version
                    )
                    if _bili_launch_attempt:
                        utils.logger.info(
                            "[BILIBILI_BROWSER_STARTUP] persistent browser retry succeeded"
                        )
                    return browser_context
                except TargetClosedError as _bili_launch_err:
                    _bili_launch_exc = _bili_launch_err
                    utils.logger.warning(
                        f"[BILIBILI_BROWSER_STARTUP] persistent browser attempt="
                        f"{{_bili_launch_attempt + 1}} failed type={{type(_bili_launch_err).__name__}}"
                    )
                    if _bili_launch_attempt < 1:
                        await asyncio.sleep(2)
            raise _bili_launch_exc
'''
        text = replace_once(text, old, new, "Bilibili persistent browser retry")

    write_py(path, text)

def patch_login(root: Path) -> None:
    path = root / "media_platform/bilibili/login.py"
    text = read(path)
    if f"# {MARKER}: resilient official login UI" in text:
        return

    old = '''        # click login button
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
'''
    new = f'''        # {MARKER}: resilient official login UI.
        # Bilibili can render the login modal before the header click completes;
        # in that state .bili-mini-mask/.toast__mask intercept the old locator.
        # Detect an already-open QR modal first, otherwise use bounded selectors
        # for Bilibili's normal login control. This never bypasses captcha or
        # security verification.
        qrcode_img_selector = "//div[@class='login-scan-box']//img"

        async def _bili_qr_visible() -> bool:
            try:
                qr = self.context_page.locator(f"xpath={{qrcode_img_selector}}").first
                return await qr.count() > 0 and await qr.is_visible()
            except Exception:
                return False

        login_open = await _bili_qr_visible()
        login_selectors = (
            "xpath=//div[contains(@class,'go-login-btn')]//*[normalize-space(text())='登录']",
            "xpath=//div[contains(@class,'go-login-btn')]",
            "button:has-text('登录')",
            "[role='button']:has-text('登录')",
            "text=登录",
        )

        if not login_open:
            for selector in login_selectors:
                try:
                    candidate = self.context_page.locator(selector).first
                    if await candidate.count() <= 0 or not await candidate.is_visible():
                        continue

                    # Give transient Bilibili toast/mini-login masks a short chance
                    # to disappear. If the QR modal appeared meanwhile, no click is
                    # needed and the normal login flow can continue.
                    for _ in range(4):
                        if await _bili_qr_visible():
                            login_open = True
                            break
                        await asyncio.sleep(0.5)
                    if login_open:
                        break

                    await candidate.click(timeout=8000)
                    await asyncio.sleep(1)
                    if await _bili_qr_visible():
                        login_open = True
                        utils.logger.info(
                            f"[BILIBILI_LOGIN_UI] opened official QR login selector={{selector}}"
                        )
                        break
                except Exception as exc:
                    if await _bili_qr_visible():
                        login_open = True
                        utils.logger.info(
                            "[BILIBILI_LOGIN_UI] QR modal became visible while click was intercepted"
                        )
                        break
                    utils.logger.info(
                        f"[BILIBILI_LOGIN_UI] selector failed type={{type(exc).__name__}} selector={{selector}}"
                    )

        if not login_open:
            utils.logger.warning(
                "[BILIBILI_LOGIN_REQUIRED] official QR login control/modal is unavailable. "
                "Complete normal Bilibili login/security verification manually, then rerun."
            )
            raise RuntimeError(
                "BILIBILI_LOGIN_REQUIRED: official login UI unavailable; manual login required"
            )

        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
'''
    text = replace_once(text, old, new, "Bilibili official login UI resilience")
    write_py(path, text)


def check(root: Path) -> dict:
    core = root / "media_platform/bilibili/core.py"
    login = root / "media_platform/bilibili/login.py"
    result = {
        "patch_version": 3,
        "core_exists": core.exists(),
        "login_exists": login.exists(),
        "session_probe_retry": False,
        "existing_qr_detection": False,
        "selector_fallback": False,
        "bounded_click_timeout": False,
        "manual_login_marker": False,
        "standard_browser_mode": False,
        "persistent_launch_retry": False,
        "bounded_home_navigation": False,
        "ok": False,
    }
    if not core.exists() or not login.exists():
        return result

    try:
        core_text = read(core)
        login_text = read(login)
        ast.parse(core_text, filename=str(core))
        ast.parse(login_text, filename=str(login))
        result["session_probe_retry"] = (
            f"# {MARKER}: bounded session probe" in core_text
            and "for _bili_pong_attempt in range(3):" in core_text
            and "[BILIBILI_SESSION_PROBE]" in core_text
        )
        result["existing_qr_detection"] = (
            f"# {MARKER}: resilient official login UI" in login_text
            and "_bili_qr_visible" in login_text
            and "login_open = await _bili_qr_visible()" in login_text
        )
        result["selector_fallback"] = (
            "button:has-text('登录')" in login_text
            and "[role='button']:has-text('登录')" in login_text
        )
        result["bounded_click_timeout"] = "candidate.click(timeout=8000)" in login_text
        result["manual_login_marker"] = (
            "BILIBILI_LOGIN_REQUIRED" in core_text
            and "BILIBILI_LOGIN_REQUIRED" in login_text
        )
        result["standard_browser_mode"] = (
            f"# {STARTUP_MARKER}: use standard persistent browser" in core_text
            and "[BILIBILI_BROWSER_STARTUP] using standard persistent browser mode" in core_text
        )
        result["persistent_launch_retry"] = (
            f"# {STARTUP_MARKER}: bounded persistent-context retry" in core_text
            and "for _bili_launch_attempt in range(2):" in core_text
        )
        result["bounded_home_navigation"] = (
            f"# {NAVIGATION_MARKER}: bounded homepage navigation" in core_text
            and 'wait_until="domcontentloaded"' in core_text
            and "timeout=15000" in core_text
            and "[BILIBILI_HOME_NAVIGATION_DEGRADED]" in core_text
        )
        result["ok"] = all([
            result["session_probe_retry"],
            result["existing_qr_detection"],
            result["selector_fallback"],
            result["bounded_click_timeout"],
            result["manual_login_marker"],
            result["standard_browser_mode"],
            result["persistent_launch_retry"],
            result["bounded_home_navigation"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch Bilibili session/login startup resilience without bypassing official verification."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_core(root)
            patch_login(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps({
        "root": str(root),
        **result,
        "purpose": "bilibili_standard_persistent_browser_plus_session_and_official_login_resilience",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
