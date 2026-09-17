from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _platform_root(cfg: dict) -> Path:
    root = Path(str(cfg.get("data_root") or ""))
    if root.name.endswith("_ks"):
        return root
    candidate = root.parent / f"{root.name}_ks"
    if candidate.exists():
        return candidate
    return root


def _read(path: Path, max_chars: int = 50000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]
    except Exception:
        return ""


def _matching_lines(text: str, patterns: tuple[str, ...], limit: int = 20) -> list[str]:
    rows: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(p in low for p in patterns):
            cleaned = re.sub(r"(?i)(cookie|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", line)
            rows.append(cleaned[-1000:])
    return rows[-limit:]


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose the latest failed Kuaishou monitoring cycle from local stdout/stderr logs.")
    ap.add_argument("--config", default="config/monitoring.ks-realtime-test.json")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_json(cfg_path)
    if not cfg:
        print(json.dumps({"ok": False, "error": "config_not_readable", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2

    root = _platform_root(cfg)
    status_path = root / "status" / "latest_status.json"
    status = _load_json(status_path)
    run = (status.get("platform_runs") or [{}])[0]

    stdout_path = Path(str(run.get("stdout_log") or "")) if run.get("stdout_log") else None
    stderr_path = Path(str(run.get("stderr_log") or "")) if run.get("stderr_log") else None
    stdout = _read(stdout_path) if stdout_path else ""
    stderr = _read(stderr_path) if stderr_path else ""
    combined = "\n".join([stdout, stderr])
    low = combined.lower()

    groups = {
        "login_or_session": (
            "login required", "scan code", "qrcode", "扫码", "登录失效", "需要登录", "pong kuaishou failed",
        ),
        "verification": (
            "captcha", "security verification", "verify_required", "验证码", "安全验证", "滑块",
        ),
        "kuaishou_signature_or_api": (
            "__ns_hxfalcon", "__ks_realm", "rest api v2 error", "result:50", "result: 50", '"result":50', '"result": 50',
            "wait_for_function", "$encode", "sign",
        ),
        "rate_limit": (
            "rate limited", "result:2", "result: 2", '"result":2', '"result": 2',
        ),
        "network_transport": (
            "connecttimeout", "readtimeout", "timed out", "timeouterror", "err_timed_out",
            "err_connection_reset", "err_connection_refused", "err_network_changed", "connection reset",
            "connection refused", "httpx.connecterror", "httpx.readtimeout", "temporary failure in name resolution",
            "name or service not known", "nodename nor servname", "http 502", "http 503", "http 504",
        ),
        "browser_or_playwright": (
            "targetclosederror", "browser has been closed", "context has been closed", "page has been closed",
            "playwright", "browser closed",
        ),
        "platform_data_fetch": (
            "datafetcherror", "search info by keyword", "not found data", "api returned business error",
        ),
    }

    matches = {name: _matching_lines(combined, pats) for name, pats in groups.items()}
    active = [name for name, lines in matches.items() if lines]

    if "verification" in active:
        primary = "VERIFY_REQUIRED"
    elif "login_or_session" in active:
        primary = "LOGIN_OR_SESSION"
    elif "rate_limit" in active:
        primary = "KUAISHOU_RATE_LIMIT"
    elif "kuaishou_signature_or_api" in active:
        primary = "KUAISHOU_SIGNATURE_OR_API"
    elif "network_transport" in active:
        primary = "NETWORK_TRANSPORT"
    elif "browser_or_playwright" in active:
        primary = "BROWSER_OR_PLAYWRIGHT"
    elif "platform_data_fetch" in active:
        primary = "PLATFORM_DATA_FETCH"
    elif combined.strip():
        primary = "UNCLASSIFIED_CRAWLER_FAILURE"
    else:
        primary = "NO_LOG_TEXT"

    tail_lines = [line for line in combined.splitlines() if line.strip()][-40:]
    result = {
        "ok": True,
        "platform": "ks",
        "config": str(cfg_path),
        "data_root": str(root),
        "latest_status": str(status_path),
        "reported_state": run.get("state"),
        "return_code": run.get("return_code"),
        "content_rows": run.get("content_row_count", 0),
        "comment_rows": run.get("comment_row_count", 0),
        "stdout_log": str(stdout_path or ""),
        "stderr_log": str(stderr_path or ""),
        "primary_diagnosis": primary,
        "active_signal_groups": active,
        "matches": matches,
        "tail": tail_lines,
        "note": (
            "This diagnostic only classifies the local failure logs. It does not retry, bypass login/captcha, "
            "or fabricate data. Complete official platform verification manually when requested."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
