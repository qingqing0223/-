from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V3"
LEGACY_MARKERS = (
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V1",
    "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V2",
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


def _find_all(text: str, needle: str) -> list[int]:
    positions: list[int] = []
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            break
        positions.append(idx)
        pos = idx + len(needle)
    return positions


def _line_bounds(text: str, index: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end < 0:
        end = len(text)
    else:
        end += 1
    return start, end


def _startup_window(text: str, path: Path) -> tuple[int, int]:
    """Return the exact Kuaishou startup bootstrap window without relying on indentation."""
    left_token = "await self.context_page.add_init_script(KS_SIGN_CAPTURE_SCRIPT)"
    right_token = "# Create a client to interact with the kuaishou website."

    left_positions = _find_all(text, left_token)
    if len(left_positions) != 1:
        raise RuntimeError(
            f"{path}: expected exactly one KS_SIGN_CAPTURE_SCRIPT startup anchor, found {len(left_positions)}"
        )

    _, left_line_end = _line_bounds(text, left_positions[0])
    right_index = text.find(right_token, left_line_end)
    if right_index < 0:
        raise RuntimeError(f"{path}: Kuaishou client-creation anchor not found after startup script injection")
    right_line_start, _ = _line_bounds(text, right_index)
    return left_line_end, right_line_start


def _goto_line_in_window(window: str, path: Path) -> tuple[int, int, str]:
    token = 'await self.context_page.goto(f"{self.index_url}?isHome=1")'
    positions = _find_all(window, token)
    if len(positions) != 1:
        raise RuntimeError(
            f"{path}: expected exactly one Kuaishou homepage navigation inside startup window, found {len(positions)}; "
            "other identical goto calls elsewhere in core.py are intentionally ignored"
        )
    line_start, line_end = _line_bounds(window, positions[0])
    line = window[line_start:line_end]
    indent = line[: len(line) - len(line.lstrip(" \t"))]
    return line_start, line_end, indent


def patch_core(root: Path) -> None:
    path = root / "media_platform/kuaishou/core.py"
    text = _read(path)

    if MARKER in text:
        return

    # Older resilience versions are already functionally safe. Upgrade their
    # marker in place rather than stacking another retry block.
    if 'wait_until="domcontentloaded"' in text and "for navigation_attempt in range(2):" in text:
        for legacy in LEGACY_MARKERS:
            if legacy in text:
                text = text.replace(legacy, MARKER, 1)
                _write(path, text)
                return

    start, end = _startup_window(text, path)
    window = text[start:end]

    if 'wait_until="domcontentloaded"' in window and "for navigation_attempt in range(2):" in window:
        first_nonempty = next((ln for ln in window.splitlines() if ln.strip()), "")
        indent = first_nonempty[: len(first_nonempty) - len(first_nonempty.lstrip(" \t"))]
        insertion = f"{indent}# {MARKER}: adopted existing resilient Kuaishou homepage navigation.\n"
        text = text[:start] + insertion + text[start:]
        _write(path, text)
        return

    line_start, line_end, indent = _goto_line_in_window(window, path)
    patched_window = window[:line_start] + _resilient_block(indent) + window[line_end:]
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
        "purpose": "indentation_agnostic_anchor_specific_kuaishou_homepage_retry",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
