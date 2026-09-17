from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_core(root: Path) -> None:
    path = root / "media_platform/kuaishou/core.py"
    text = _read(path)
    if MARKER in text:
        return

    old = '            await self.context_page.goto(f"{self.index_url}?isHome=1")\n'
    new = (
        f'            # {MARKER}: do not wait for every homepage resource to finish.\n'
        '            # Slow ads/static assets can keep Playwright\'s default "load" event pending\n'
        '            # even though the page is already usable for login/session/bootstrap.\n'
        '            home_url = f"{self.index_url}?isHome=1"\n'
        '            for navigation_attempt in range(2):\n'
        '                try:\n'
        '                    await self.context_page.goto(\n'
        '                        home_url, wait_until="domcontentloaded", timeout=45000\n'
        '                    )\n'
        '                    break\n'
        '                except Exception as exc:\n'
        '                    if navigation_attempt >= 1:\n'
        '                        raise\n'
        '                    utils.logger.warning(\n'
        '                        f"[KuaishouCrawler.start] homepage navigation failed once: {type(exc).__name__}: {exc}; retrying"\n'
        '                    )\n'
        '                    await asyncio.sleep(2)\n'
    )
    if text.count(old) != 1:
        raise RuntimeError(
            f"{path}: expected exactly one Kuaishou homepage navigation anchor, found {text.count(old)}"
        )
    text = text.replace(old, new, 1)
    _write(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/core.py"
    result = {
        "core_exists": path.exists(),
        "marker_present": False,
        "domcontentloaded_present": False,
        "retry_present": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = _read(path)
    try:
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text
        result["domcontentloaded_present"] = 'wait_until="domcontentloaded"' in text
        result["retry_present"] = "for navigation_attempt in range(2):" in text
        result["ok"] = bool(
            result["marker_present"]
            and result["domcontentloaded_present"]
            and result["retry_present"]
        )
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch pinned MediaCrawler Kuaishou startup to tolerate slow homepage load resources."
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
        "purpose": "domcontentloaded_retry_for_kuaishou_homepage_startup",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
