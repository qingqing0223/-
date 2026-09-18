from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_LOGIN_RESILIENCE_V1"


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
    if f"# {MARKER}: bounded session probe" in text:
        return

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
        "patch_version": 1,
        "core_exists": core.exists(),
        "login_exists": login.exists(),
        "session_probe_retry": False,
        "existing_qr_detection": False,
        "selector_fallback": False,
        "bounded_click_timeout": False,
        "manual_login_marker": False,
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
        result["ok"] = all([
            result["session_probe_retry"],
            result["existing_qr_detection"],
            result["selector_fallback"],
            result["bounded_click_timeout"],
            result["manual_login_marker"],
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
        "purpose": "bounded_bilibili_session_probe_and_official_login_ui_resilience",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
