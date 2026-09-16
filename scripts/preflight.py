from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SUQI_ROOT = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system")
SUPPORTED_PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu")


def _git(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["git", *args], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _check_json(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        _load_json(path)
        return True, "ok"
    except Exception as exc:
        return False, f"invalid json: {exc}"


def _contains(path: Path, needle: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    try:
        found = needle in path.read_text(encoding="utf-8", errors="replace")
        return found, "installed" if found else "not installed"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _dashboard_health() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3) as resp:
            return resp.status == 200, f"http {resp.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_platform_config(path: Path) -> tuple[bool, str]:
    try:
        cfg = _load_json(path)
        codes = {str(x.get("code") or "") for x in cfg.get("platforms", [])}
        missing = [x for x in SUPPORTED_PLATFORMS if x not in codes]
        if missing:
            return False, "missing platform codes: " + ",".join(missing)
        return True, "7/7 platform codes present"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_mediacrawler_platforms(root: Path) -> tuple[bool, str]:
    if not (root / "main.py").exists():
        return False, f"MediaCrawler main.py missing under {root}"
    candidates = [
        root / "config" / "base_config.py",
        root / "cmd_arg" / "arg.py",
        root / "main.py",
    ]
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in candidates if p.exists()
    )
    missing = [code for code in SUPPORTED_PLATFORMS if code not in text]
    if missing:
        return False, "local MediaCrawler code did not expose: " + ",".join(missing)
    return True, "local MediaCrawler appears to expose all 7 platform codes"


def main() -> int:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, required: bool = True):
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    add("python", True, sys.version.split()[0])
    add("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    add("uv", shutil.which("uv") is not None, shutil.which("uv") or "not found")
    add(
        "DASHSCOPE_API_KEY",
        bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()),
        "set" if os.environ.get("DASHSCOPE_API_KEY", "").strip() else "not set",
    )

    json_files = (
        "config/monitoring.windows.json",
        "config/monitoring.student.windows.json",
        "config/monitoring.region.windows.json",
        "config/monitoring.multilingual.windows.json",
        "config/multilingual_keywords.json",
        "config/key_accounts.example.json",
    )
    for rel in json_files:
        ok, detail = _check_json(ROOT / rel)
        add(rel, ok, detail)

    for rel in (
        "config/monitoring.windows.json",
        "config/monitoring.student.windows.json",
        "config/monitoring.region.windows.json",
        "config/monitoring.multilingual.windows.json",
    ):
        ok, detail = _check_platform_config(ROOT / rel)
        add(f"platform coverage:{rel}", ok, detail)

    try:
        main_cfg = _load_json(ROOT / "config" / "monitoring.windows.json")
        crawler_root = Path(main_cfg["media_crawler_root"])
        ok, detail = _check_mediacrawler_platforms(crawler_root)
        add("local MediaCrawler seven-platform support", ok, detail)
    except Exception as exc:
        add("local MediaCrawler seven-platform support", False, f"{type(exc).__name__}: {exc}")

    for module in (
        "pipeline.language_detector",
        "pipeline.normalizer",
        "pipeline.classifier",
        "monitor.ingest",
        "monitor.orchestrator",
        "monitor.result_summary",
        "dashboard_adapter.suqi_pusher",
    ):
        try:
            __import__(module)
            add(f"import:{module}", True, "ok")
        except Exception as exc:
            add(f"import:{module}", False, f"{type(exc).__name__}: {exc}")

    dashboard_ok, dashboard_detail = _dashboard_health()
    add("Suqi dashboard health", dashboard_ok, dashboard_detail, required=False)

    region_patch_ok, region_patch_detail = _contains(
        SUQI_ROOT / "db.py", "ON CONFLICT(uid) DO UPDATE SET"
    )
    add("Suqi region/engagement upsert patch", region_patch_ok, region_patch_detail, required=False)
    language_panel_ok, language_panel_detail = _contains(
        SUQI_ROOT / "web" / "index.html", "CORE_MINORITY_LANGS"
    )
    add("Suqi minority-language panel patch", language_panel_ok, language_panel_detail, required=False)
    platform_patch_ok, platform_patch_detail = _contains(
        SUQI_ROOT / "stats.py", 'g = r["platform"] or r["platform_group"] or "其他"'
    )
    add("Suqi separate-platform live statistics patch", platform_patch_ok, platform_patch_detail, required=False)

    rc, remote = _git(["remote", "get-url", "origin"])
    add("git origin", rc == 0 and bool(remote), remote or "missing", required=False)
    rc, user_name = _git(["config", "user.name"])
    add("git user.name", rc == 0 and bool(user_name), user_name or "missing", required=False)
    rc, user_email = _git(["config", "user.email"])
    add("git user.email", rc == 0 and bool(user_email), user_email or "missing", required=False)

    key_accounts_local = ROOT / "config" / "key_accounts.json"
    if key_accounts_local.exists():
        ok, detail = _check_json(key_accounts_local)
        add("config/key_accounts.json", ok, detail, required=False)
    else:
        add("config/key_accounts.json", False, "not configured yet", required=False)

    required_failures = [c for c in checks if c["required"] and not c["ok"]]
    optional_warnings = [c for c in checks if not c["required"] and not c["ok"]]
    result = {
        "ok": not required_failures,
        "supported_platforms": list(SUPPORTED_PLATFORMS),
        "required_failures": len(required_failures),
        "optional_warnings": len(optional_warnings),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
