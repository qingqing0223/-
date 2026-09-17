from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V5"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V1",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V2",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V3",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V4",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _resilient_block(indent: str) -> str:
    i1, i2, i3, i4 = indent, indent + "    ", indent + "        ", indent + "            "
    return (
        f'{i1}# {MARKER}: do not wait for every homepage resource to finish.\n'
        f'{i1}# Slow ads/static assets can keep Playwright\'s default "load" event pending.\n'
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
    return start, len(text) if end < 0 else end + 1


def _startup_window(text: str, path: Path) -> tuple[int, int]:
    """Locate only the homepage bootstrap inside Kuaishou.start()."""
    inject_anchor = "await self.context_page.add_init_script(KS_SIGN_CAPTURE_SCRIPT)"
    right_token = "# Create a client to interact with the kuaishou website."
    right_idx = text.find(right_token)
    if right_idx < 0:
        raise RuntimeError(f"{path}: Kuaishou client-creation anchor not found")
    inject_idx = text.rfind(inject_anchor, 0, right_idx)
    if inject_idx < 0:
        raise RuntimeError(f"{path}: KS_SIGN_CAPTURE_SCRIPT startup anchor not found before client creation")
    _, start = _line_bounds(text, inject_idx)
    end, _ = _line_bounds(text, right_idx)
    if start >= end:
        raise RuntimeError(f"{path}: invalid Kuaishou startup window")
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
        for legacy in LEGACY_MARKERS:
            if legacy in upgraded:
                upgraded = upgraded.replace(legacy, MARKER, 1)
                break
        else:
            first_nonempty = next((ln for ln in upgraded.splitlines() if ln.strip()), "")
            indent = first_nonempty[: len(first_nonempty) - len(first_nonempty.lstrip(" \t"))]
            upgraded = f"{indent}# {MARKER}: adopted existing resilient Kuaishou homepage navigation.\n" + upgraded
        _write(path, text[:start] + upgraded + text[end:])
        return

    matches = _raw_goto_matches(window)
    if not matches:
        raise RuntimeError(f"{path}: startup window has neither resilient navigation nor raw homepage goto")
    indent = matches[0].group("indent")
    pieces, cursor = [], 0
    for idx, match in enumerate(matches):
        pieces.append(window[cursor:match.start()])
        if idx == 0:
            pieces.append(_resilient_block(indent))
        cursor = match.end()
    pieces.append(window[cursor:])
    _write(path, text[:start] + "".join(pieces) + text[end:])


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/core.py"
    result = {
        "patch_version": 5,
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
        result["ok"] = bool(result["marker_present"] and result["domcontentloaded_present"] and result["retry_present"] and result["raw_homepage_goto_remaining"] == 0)
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch Kuaishou startup homepage navigation resilience.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_core(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "patch_version": 5, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result, "purpose": "startup_window_scoped_duplicate_tolerant_kuaishou_homepage_retry"}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
