from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def _git(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def _check_json(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True, "ok"
    except Exception as exc:
        return False, f"invalid json: {exc}"


def _dashboard_health() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3) as resp:
            return resp.status == 200, f"http {resp.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, required: bool = True):
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    add("python", True, sys.version.split()[0])
    add("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    add("uv", shutil.which("uv") is not None, shutil.which("uv") or "not found")
    add("DASHSCOPE_API_KEY", bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()), "set" if os.environ.get("DASHSCOPE_API_KEY", "").strip() else "not set")

    for rel in (
        "config/monitoring.windows.json",
        "config/monitoring.region.windows.json",
        "config/monitoring.multilingual.windows.json",
        "config/multilingual_keywords.json",
        "config/key_accounts.example.json",
    ):
        ok, detail = _check_json(ROOT / rel)
        add(rel, ok, detail)

    # Imports exercise the locally installed package and catch syntax/module errors.
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
        "required_failures": len(required_failures),
        "optional_warnings": len(optional_warnings),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
