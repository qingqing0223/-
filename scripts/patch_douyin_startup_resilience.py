from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_DY_STARTUP_RESILIENCE_V1"


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
    path = root / "media_platform/douyin/core.py"
    text = read(path)
    if f"# {MARKER}: resilient homepage bootstrap" in text:
        return

    old = "            await self.context_page.goto(self.index_url)\n"
    new = f'''            # {MARKER}: resilient homepage bootstrap.
            # Do not wait for every ad/static resource to finish loading. A slow
            # third-party resource can keep Playwright's default "load" event
            # pending even when Douyin's DOM is already usable.
            _dy_home_loaded = False
            _dy_last_nav_exc = None
            for _dy_nav_attempt in range(2):
                try:
                    await self.context_page.goto(
                        self.index_url,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    _dy_home_loaded = True
                    break
                except Exception as _dy_nav_exc:
                    _dy_last_nav_exc = _dy_nav_exc
                    utils.logger.warning(
                        f"[DOUYIN_STARTUP_NAV] attempt={{_dy_nav_attempt + 1}} "
                        f"type={{type(_dy_nav_exc).__name__}} detail={{str(_dy_nav_exc)[:240]}}"
                    )
                    if _dy_nav_attempt < 1:
                        await asyncio.sleep(2)

            if not _dy_home_loaded:
                # Final bounded fallback: require only that the main navigation
                # response commits. This does not bypass login/captcha/security
                # checks; normal session probing immediately follows.
                try:
                    await self.context_page.goto(
                        self.index_url,
                        wait_until="commit",
                        timeout=30000,
                    )
                    _dy_home_loaded = True
                    utils.logger.warning(
                        "[DOUYIN_STARTUP_NAV] domcontentloaded timed out; "
                        "continued after main navigation commit"
                    )
                except Exception as _dy_commit_exc:
                    utils.logger.error(
                        f"[DOUYIN_STARTUP_NETWORK_ERROR] homepage navigation failed "
                        f"type={{type(_dy_commit_exc).__name__}} "
                        f"detail={{str(_dy_commit_exc)[:240]}}"
                    )
                    raise _dy_commit_exc from _dy_last_nav_exc
'''
    text = replace_once(text, old, new, "Douyin homepage navigation")
    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/douyin/core.py"
    result = {
        "patch_version": 1,
        "core_exists": path.exists(),
        "marker_present": False,
        "domcontentloaded_present": False,
        "retry_present": False,
        "commit_fallback_present": False,
        "raw_default_goto_remaining": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["marker_present"] = f"# {MARKER}: resilient homepage bootstrap" in text
        result["domcontentloaded_present"] = 'wait_until="domcontentloaded"' in text
        result["retry_present"] = "for _dy_nav_attempt in range(2):" in text
        result["commit_fallback_present"] = 'wait_until="commit"' in text
        result["raw_default_goto_remaining"] = "await self.context_page.goto(self.index_url)\n" in text
        result["ok"] = all([
            result["marker_present"],
            result["domcontentloaded_present"],
            result["retry_present"],
            result["commit_fallback_present"],
            not result["raw_default_goto_remaining"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch Douyin homepage startup navigation resilience without bypassing official verification."
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
        print(json.dumps({
            "ok": False,
            "root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "root": str(root),
        **result,
        "purpose": "bounded_douyin_homepage_navigation_retry_no_verification_bypass",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
