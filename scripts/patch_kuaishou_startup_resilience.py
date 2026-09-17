from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V4"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V1",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V2",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V3",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _resilient_block(indent: str) -> str:
    i1 = indent
    i2 = indent + "    "
    i3 = indent + "        "
    i4 = indent + "            "
    return (
        f'{i1}# {MARKER}: do not wait for every homepage resource to finish.\n'
        f'{i1}# Slow ads/static assets can keep Playwright\'s default "load" event pending\n'
        f'{i1}# even though the page is already usable for login/session/bootstrap.\n'
        f'{i1}home_url = f"{{self.index_url}}?isHome=1"\n'
        f'{i1}for navigation_attempt in range(2):\n'
        f'{i2}try:\n'
        f'{i3}await self.context_page.goto(\n'
        f'{i4}home_url, wait_until="domcontentloaded", timeout=45000\n'
        f'{i3})\n'
        f'{i3}break\n'
        f'{i2}except Exception as exc:\n'
        f'{i3}if navigation_attempt >= 1:\n'
        f'{i4}raise\n'
        f'{i3}utils.logger.warning(\n'
        f'{i4}f"[KuaishouCrawler.start] homepage navigation failed once: {{type(exc).__name__}}: {{exc}}; retrying"\n'
        f'{i3})\n'
        f'{i3}await asyncio.sleep(2)\n'
    )


def _line_bounds(text: str, index: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end < 0:
        end = len(text)
    else:
        end += 1
    return start, end


def _startup_window(text: str, path: Path) -> tuple[int, int]:
    """Locate only Kuaishou.start() bootstrap code around the first context page.

    The upstream file can contain additional homepage goto calls in helper/fallback
    paths.  Those must not make this patch fail.  We deliberately scope matching to
    the page-creation -> client-creation window used by start().
    """
    page_anchor = "self.context_page = await self.browser_context.new_page()"
    inject_anchor = "await self.context_page.add_init_script(KS_SIGN_CAPTURE_SCRIPT)"
    right_token = "# Create a client to interact with the kuaishou website."

    page_idx = text.find(page_anchor)
    if page_idx < 0:
        raise RuntimeError(f"{path}: Kuaishou context-page creation anchor not found")

    inject_idx = text.find(inject_anchor, page_idx)
    if inject_idx < 0:
        raise RuntimeError(f"{path}: KS_SIGN_CAPTURE_SCRIPT startup anchor not found after page creation")

    _, start = _line_bounds(text, inject_idx)
    right_idx = text.find(right_token, start)
    if right_idx < 0:
        raise RuntimeError(f"{path}: Kuaishou client-creation anchor not found after startup injection")
    end, _ = _line_bounds(text, right_idx)
    return start, end


def _raw_goto_matches(window: str) -> list[re.Match[str]]:
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)await\s+self\.context_page\.goto\(\s*'
        r'f["\']\{self\.index_url\}\?isHome=1["\']\s*\)\s*\r?\n?'
    )
    return list(pattern.finditer(window))


def patch_core(root: Path) -> None:
    path = root / "media_platform/kuaishou/core.py"
    text = _read(path)
    start, end = _startup_window(text, path)
    window = text[start:end]

    resilient = 'wait_until="domcontentloaded"' in window and "for navigation_attempt in range(2):" in window
    if resilient:
        if MARKER in window:
            return
        upgraded = window
        replaced = False
        for legacy in LEGACY_MARKERS:
            if legacy in upgraded:
                upgraded = upgraded.replace(legacy, MARKER, 1)
                replaced = True
                break
        if not replaced:
            first_nonempty = next((ln for ln in upgraded.splitlines() if ln.strip()), "")
            indent = first_nonempty[: len(first_nonempty) - len(first_nonempty.lstrip(" \t"))]
            upgraded = f"{indent}# {MARKER}: adopted existing resilient Kuaishou homepage navigation.\n" + upgraded
        text = text[:start] + upgraded + text[end:]
        _write(path, text)
        return

    matches = _raw_goto_matches(window)
    if not matches:
        raise RuntimeError(
            f"{path}: Kuaishou startup window has neither resilient navigation nor a raw homepage goto anchor"
        )

    # Patch the first startup goto and remove any exact duplicate raw goto lines in
    # the same bootstrap window.  Identical calls elsewhere in core.py are ignored.
    first = matches[0]
    indent = first.group("indent")
    pieces = []
    cursor = 0
    for idx, match in enumerate(matches):
        pieces.append(window[cursor:match.start()])
        if idx == 0:
            pieces.append(_resilient_block(indent))
        cursor = match.end()
    pieces.append(window[cursor:])
    patched_window = "".join(pieces)
    text = text[:start] + patched_window + text[end:]
    _write(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/core.py"
    result = {
        "patch_version": 4,
        "core_exists": path.exists(),
        "marker_present": False,
        "domcontentloaded_present": False,
        "retry_present": False,
        "startup_window_valid": False,
        "raw_homepage_goto_remaining": None,
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
        result["raw_homepage_goto_remaining"] = len(_raw_goto_matches(window))
        result["startup_window_valid"] = True
        result["ok"] = bool(
            result["marker_present"]
            and result["domcontentloaded_present"]
            and result["retry_present"]
            and result["startup_window_valid"]
            and result["raw_homepage_goto_remaining"] == 0
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
            "patch_version": 4,
            "root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "root": str(root),
        **result,
        "purpose": "startup_window_scoped_duplicate_tolerant_kuaishou_homepage_retry",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
