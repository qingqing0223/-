from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V2"
LEGACY_MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _resilient_block() -> str:
    return (
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


def _startup_window(text: str, path: Path) -> tuple[int, int]:
    """Return the exact Kuaishou startup bootstrap window.

    The same homepage goto may appear elsewhere in a locally patched MediaCrawler
    tree.  We only modify the navigation immediately after KS_SIGN_CAPTURE_SCRIPT
    injection and before client creation.  This keeps the patch deterministic even
    when another identical goto exists elsewhere in core.py.
    """
    left_anchor = "            await self.context_page.add_init_script(KS_SIGN_CAPTURE_SCRIPT)\n"
    right_anchor = "            # Create a client to interact with the kuaishou website.\n"

    left_positions: list[int] = []
    pos = 0
    while True:
        idx = text.find(left_anchor, pos)
        if idx < 0:
            break
        left_positions.append(idx)
        pos = idx + len(left_anchor)
    if len(left_positions) != 1:
        raise RuntimeError(
            f"{path}: expected exactly one KS_SIGN_CAPTURE_SCRIPT startup anchor, found {len(left_positions)}"
        )

    start = left_positions[0] + len(left_anchor)
    end = text.find(right_anchor, start)
    if end < 0:
        raise RuntimeError(f"{path}: Kuaishou client-creation anchor not found after startup script injection")
    return start, end


def patch_core(root: Path) -> None:
    path = root / "media_platform/kuaishou/core.py"
    text = _read(path)

    # Already on V2: fully idempotent.
    if MARKER in text:
        return

    # A previous V1 patch is already functionally resilient. Upgrade only its
    # marker so repeated setup/checks agree on the current patch version.
    if LEGACY_MARKER in text and 'wait_until="domcontentloaded"' in text and "for navigation_attempt in range(2):" in text:
        text = text.replace(LEGACY_MARKER, MARKER, 1)
        _write(path, text)
        return

    start, end = _startup_window(text, path)
    window = text[start:end]

    # If another local patch already introduced the same resilient navigation but
    # omitted our marker, adopt it rather than inserting a second retry loop.
    if 'wait_until="domcontentloaded"' in window and "for navigation_attempt in range(2):" in window:
        insertion = f"            # {MARKER}: adopted existing resilient Kuaishou homepage navigation.\n"
        text = text[:start] + insertion + text[start:]
        _write(path, text)
        return

    old = '            await self.context_page.goto(f"{self.index_url}?isHome=1")\n'
    count_in_window = window.count(old)
    if count_in_window != 1:
        raise RuntimeError(
            f"{path}: expected exactly one Kuaishou homepage navigation inside startup window, found {count_in_window}; "
            "other identical goto calls elsewhere in core.py are intentionally ignored"
        )

    patched_window = window.replace(old, _resilient_block(), 1)
    text = text[:start] + patched_window + text[end:]
    _write(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/core.py"
    result = {
        "core_exists": path.exists(),
        "marker_present": False,
        "domcontentloaded_present": False,
        "retry_present": False,
        "startup_window_valid": False,
        "ok": False,
    }
    if not path.exists():
        return result
    text = _read(path)
    try:
        ast.parse(text, filename=str(path))
        start, end = _startup_window(text, path)
        window = text[start:end]
        result["marker_present"] = MARKER in window
        result["domcontentloaded_present"] = 'wait_until="domcontentloaded"' in window
        result["retry_present"] = "for navigation_attempt in range(2):" in window
        result["startup_window_valid"] = True
        result["ok"] = bool(
            result["marker_present"]
            and result["domcontentloaded_present"]
            and result["retry_present"]
            and result["startup_window_valid"]
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
        "purpose": "anchor_specific_domcontentloaded_retry_for_kuaishou_homepage_startup",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
