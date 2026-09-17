from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_LOGIN_RESILIENCE_V1"


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
    path = root / "media_platform/kuaishou/core.py"
    text = read(path)
    if f"# {MARKER}: session probe retry" in text:
        return

    old = '''            if not await self.ks_client.pong():
                login_obj = KuaishouLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone=httpx_proxy_format,
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.ks_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )
'''
    new = f'''            # {MARKER}: session probe retry before treating a transient API failure as logout.
            _ks_pong_ok = False
            for _ks_pong_attempt in range(3):
                try:
                    if await self.ks_client.pong():
                        _ks_pong_ok = True
                        break
                except Exception as _ks_pong_exc:
                    utils.logger.warning(
                        f"[KUAISHOU_SESSION_PROBE] attempt={{_ks_pong_attempt + 1}} "
                        f"type={{type(_ks_pong_exc).__name__}}"
                    )
                if _ks_pong_attempt < 2:
                    await asyncio.sleep(2)

            if not _ks_pong_ok:
                utils.logger.warning(
                    "[KUAISHOU_LOGIN_REQUIRED] session probe failed after bounded retries; "
                    "opening the official login flow"
                )
                login_obj = KuaishouLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone=httpx_proxy_format,
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.ks_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )
'''
    text = replace_once(text, old, new, "Kuaishou bounded session probe")
    write_py(path, text)


def patch_login(root: Path) -> None:
    path = root / "media_platform/kuaishou/login.py"
    text = read(path)
    if f"# {MARKER}: resilient official login button lookup" in text:
        return

    old = '''        # click login button
        login_button_ele = self.context_page.locator(
            "xpath=//p[text()='登录']"
        )
        await login_button_ele.click()
'''
    new = f'''        # {MARKER}: resilient official login button lookup.
        # This only opens Kuaishou's normal login UI; it never bypasses captcha/security checks.
        login_selectors = (
            "xpath=//p[normalize-space(text())='登录']",
            "button:has-text('登录')",
            "[role='button']:has-text('登录')",
            "text=登录",
        )
        login_clicked = False
        for ui_attempt in range(2):
            for selector in login_selectors:
                try:
                    candidate = self.context_page.locator(selector).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        await candidate.click(timeout=8000)
                        utils.logger.info(
                            f"[KUAISHOU_LOGIN_UI] clicked official login control selector={{selector}}"
                        )
                        login_clicked = True
                        break
                except Exception as exc:
                    utils.logger.info(
                        f"[KUAISHOU_LOGIN_UI] selector failed type={{type(exc).__name__}} selector={{selector}}"
                    )
            if login_clicked:
                break
            if ui_attempt == 0:
                try:
                    await self.context_page.goto(
                        "https://www.kuaishou.com/?isHome=1",
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    await asyncio.sleep(2)
                except Exception as exc:
                    utils.logger.warning(
                        f"[KUAISHOU_LOGIN_UI] homepage refresh failed type={{type(exc).__name__}}"
                    )

        if not login_clicked:
            utils.logger.warning(
                "[KUAISHOU_LOGIN_REQUIRED] official login control is unavailable. "
                "Complete normal Kuaishou login/security verification manually, then rerun."
            )
            raise RuntimeError(
                "KUAISHOU_LOGIN_REQUIRED: official login control unavailable; manual login required"
            )
'''
    text = replace_once(text, old, new, "Kuaishou official login button resilience")
    write_py(path, text)


def check(root: Path) -> dict:
    core = root / "media_platform/kuaishou/core.py"
    login = root / "media_platform/kuaishou/login.py"
    result = {
        "patch_version": 1,
        "core_exists": core.exists(),
        "login_exists": login.exists(),
        "session_probe_retry": False,
        "login_selector_fallback": False,
        "manual_login_marker": False,
        "bounded_click_timeout": False,
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
            f"# {MARKER}: session probe retry" in core_text
            and "for _ks_pong_attempt in range(3):" in core_text
            and "[KUAISHOU_SESSION_PROBE]" in core_text
        )
        result["login_selector_fallback"] = (
            f"# {MARKER}: resilient official login button lookup" in login_text
            and "button:has-text('登录')" in login_text
            and "[role='button']:has-text('登录')" in login_text
        )
        result["manual_login_marker"] = "KUAISHOU_LOGIN_REQUIRED" in core_text and "KUAISHOU_LOGIN_REQUIRED" in login_text
        result["bounded_click_timeout"] = "candidate.click(timeout=8000)" in login_text
        result["ok"] = all([
            result["session_probe_retry"],
            result["login_selector_fallback"],
            result["manual_login_marker"],
            result["bounded_click_timeout"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch Kuaishou session/login startup resilience without bypassing official verification.")
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
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
