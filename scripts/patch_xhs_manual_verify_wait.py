from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_XHS_MANUAL_VERIFY_WAIT_V2"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_core(root: Path) -> None:
    path = root / "media_platform/xhs/core.py"
    text = read(path)
    if MARKER in text:
        return

    helper_anchor = '''    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
'''
    helper = '''    async def _promotion_week_wait_for_manual_verification(self, seconds: int = 180) -> None:
        """Keep the official browser open while the operator completes XHS verification.

        This deliberately does not solve, bypass, or automate CAPTCHA/security
        verification. It only keeps the Playwright/CDP session alive long enough
        for a person to finish the platform's official verification UI.
        """
        # PROMOTION_WEEK_XHS_MANUAL_VERIFY_WAIT_V2
        seconds = max(30, min(int(seconds), 300))
        utils.logger.warning(
            "[XiaoHongShuCrawler] XHS official login/security verification is required. "
            f"The browser will stay open for up to {seconds} seconds. "
            "Complete verification manually in the official UI. "
            "On Windows, press ENTER in this console after verification to retry early."
        )
        for remaining in range(seconds, 0, -1):
            if remaining in (seconds, 120, 60, 30, 10):
                utils.logger.warning(
                    f"[XiaoHongShuCrawler] Waiting for manual verification: {remaining}s remaining"
                )
            try:
                if os.name == "nt":
                    import msvcrt
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ("\\r", "\\n"):
                            utils.logger.info(
                                "[XiaoHongShuCrawler] ENTER received; refreshing cookies and retrying."
                            )
                            break
            except Exception:
                pass
            await asyncio.sleep(1)

        await self.xhs_client.update_cookies(
            browser_context=self.browser_context,
            urls=self.cookie_urls,
        )

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
'''
    if helper_anchor not in text:
        raise RuntimeError("helper anchor not found")
    text = text.replace(helper_anchor, helper, 1)

    pong_old = '''            # Create a client to interact with the Xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
            if not await self.xhs_client.pong():
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass
'''
    pong_new = '''            # Create a client to interact with the Xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)

            # PROMOTION_WEEK_XHS_MANUAL_VERIFY_WAIT_V2:
            # XHS may request official account/security verification before the
            # normal login check completes. Keep the browser alive for manual
            # completion instead of immediately tearing down Playwright.
            _promotion_logged_in = False
            for _promotion_login_attempt in range(2):
                try:
                    _promotion_logged_in = await self.xhs_client.pong()
                    break
                except PlatformAccessError as ex:
                    if "XHS_VERIFY_REQUIRED" not in str(ex) or _promotion_login_attempt >= 1:
                        raise
                    await self._promotion_week_wait_for_manual_verification(180)

            if not _promotion_logged_in:
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            crawler_type_var.set(config.CRAWLER_TYPE)
            for _promotion_run_attempt in range(2):
                try:
                    if config.CRAWLER_TYPE == "search":
                        # Search for notes and retrieve their comment information.
                        await self.search()
                    elif config.CRAWLER_TYPE == "detail":
                        # Get the information and comments of the specified post
                        await self.get_specified_notes()
                    elif config.CRAWLER_TYPE == "creator":
                        # Get creator's information and their notes and comments
                        await self.get_creators_and_notes()
                    break
                except PlatformAccessError as ex:
                    if "XHS_VERIFY_REQUIRED" not in str(ex) or _promotion_run_attempt >= 1:
                        raise
                    await self._promotion_week_wait_for_manual_verification(180)
'''
    if pong_old not in text:
        raise RuntimeError("start/login dispatch anchor not found")
    text = text.replace(pong_old, pong_new, 1)

    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/xhs/core.py"
    result = {
        "core_exists": path.exists(),
        "marker_present": False,
        "manual_wait_helper": False,
        "login_guard_wait": False,
        "crawler_guard_wait": False,
        "enter_to_retry": False,
        "bounded_wait": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text
        result["manual_wait_helper"] = "_promotion_week_wait_for_manual_verification" in text
        result["login_guard_wait"] = "_promotion_login_attempt" in text
        result["crawler_guard_wait"] = "_promotion_run_attempt" in text
        result["enter_to_retry"] = "msvcrt.kbhit()" in text
        result["bounded_wait"] = "max(30, min(int(seconds), 300))" in text
        result["ok"] = all(result[k] for k in (
            "marker_present",
            "manual_wait_helper",
            "login_guard_wait",
            "crawler_guard_wait",
            "enter_to_retry",
            "bounded_wait",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Keep the XHS official browser open during login/security verification so "
            "the operator can complete it manually. No CAPTCHA bypass is performed."
        )
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_core(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
            indent=2,
        ))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
