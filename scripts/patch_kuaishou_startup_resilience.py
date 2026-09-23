from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_KS_STARTUP_RESILIENCE_V6"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


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


def _indent_for_window(window: str) -> str:
    for line in window.splitlines():
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return "            "


def _resilient_block(indent: str) -> str:
    i1 = indent
    i2 = indent + "    "
    i3 = indent + "        "
    i4 = indent + "            "
    return (
        f'{i1}# {MARKER}: use response commit as the hard startup boundary.\n'
        f'{i1}# Kuaishou can keep DOMContentLoaded pending or abort a second goto even when\n'
        f'{i1}# the browser has already reached kuaishou.com.  Treat DOM readiness as best-effort.\n'
        f'{i1}home_url = f"{{self.index_url}}?isHome=1"\n'
        f'{i1}try:\n'
        f'{i2}await self.context_page.goto(\n'
        f'{i3}home_url, wait_until="commit", timeout=20000\n'
        f'{i2})\n'
        f'{i1}except Exception as exc:\n'
        f'{i2}current_url = str(self.context_page.url or "")\n'
        f'{i2}if "kuaishou.com" not in current_url:\n'
        f'{i3}utils.logger.warning(\n'
        f'{i4}f"[KuaishouCrawler.start] homepage commit failed: {{type(exc).__name__}}: {{exc}}; retrying base URL once"\n'
        f'{i3})\n'
        f'{i3}try:\n'
        f'{i4}await self.context_page.goto(\n'
        f'{i4}    self.index_url, wait_until="commit", timeout=15000\n'
        f'{i4})\n'
        f'{i3}except Exception as retry_exc:\n'
        f'{i4}current_url = str(self.context_page.url or "")\n'
        f'{i4}if "kuaishou.com" not in current_url:\n'
        f'{i4}    raise\n'
        f'{i4}utils.logger.warning(\n'
        f'{i4}    f"[KuaishouCrawler.start] base URL retry raised after site commit: {{type(retry_exc).__name__}}: {{retry_exc}}; continuing"\n'
        f'{i4})\n'
        f'{i2}else:\n'
        f'{i3}utils.logger.warning(\n'
        f'{i4}f"[KuaishouCrawler.start] homepage goto raised after site commit: {{type(exc).__name__}}: {{exc}}; continuing"\n'
        f'{i3})\n'
        f'{i1}try:\n'
        f'{i2}await self.context_page.wait_for_load_state("domcontentloaded", timeout=12000)\n'
        f'{i1}except Exception as exc:\n'
        f'{i2}utils.logger.warning(\n'
        f'{i3}f"[KuaishouCrawler.start] DOM readiness is still pending: {{type(exc).__name__}}: {{exc}}; continuing with loaded page state"\n'
        f'{i2})\n'
        f'{i1}await asyncio.sleep(2)\n'
    )


def patch_core(root: Path) -> None:
    path = root / "media_platform/kuaishou/core.py"
    text = _read(path)
    start, end = _startup_window(text, path)
    window = text[start:end]

    if MARKER in window and 'wait_until="commit"' in window:
        return

    indent = _indent_for_window(window)
    replacement = _resilient_block(indent)
    _write(path, text[:start] + replacement + text[end:])


def check(root: Path) -> dict:
    path = root / "media_platform/kuaishou/core.py"
    result = {
        "patch_version": 6,
        "core_exists": path.exists(),
        "marker_present": False,
        "commit_navigation_present": False,
        "best_effort_dom_present": False,
        "site_commit_tolerance_present": False,
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
        result["commit_navigation_present"] = 'wait_until="commit"' in window
        result["best_effort_dom_present"] = (
            'wait_for_load_state("domcontentloaded", timeout=12000)' in window
        )
        result["site_commit_tolerance_present"] = (
            '"kuaishou.com" not in current_url' in window
            and "homepage goto raised after site commit" in window
        )
        result["startup_window_valid"] = True
        result["ok"] = all([
            result["marker_present"],
            result["commit_navigation_present"],
            result["best_effort_dom_present"],
            result["site_commit_tolerance_present"],
            result["startup_window_valid"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch Kuaishou startup navigation so partial homepage loads do not abort collection.")
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
            {"ok": False, "patch_version": 6, "root": str(root), "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
            indent=2,
        ))
        return 2
    print(json.dumps(
        {
            "root": str(root),
            **result,
            "purpose": "commit_bounded_kuaishou_homepage_navigation_with_best_effort_dom",
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
