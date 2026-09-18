from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opinion_monitor_v2 import OpinionMonitorV2


def _classify_failure(text: str) -> str:
    low = text.lower()
    if "api key missing" in low or ("dashscope_api_key" in low and "missing" in low):
        return "API_KEY_MISSING"
    if "arrearage" in low or "overdue-payment" in low or "account is in good standing" in low:
        return "ACCOUNT_ARREARS"
    if "quota" in low or ("insufficient" in low and "balance" in low):
        return "QUOTA_OR_BALANCE"
    if "429" in low or "rate limit" in low:
        return "RATE_LIMIT"
    if "network" in low or "timeout" in low or "timed out" in low:
        return "NETWORK"
    if "http 4" in low:
        return "HTTP_CLIENT_ERROR"
    if "http 5" in low:
        return "HTTP_SERVER_ERROR"
    return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser(description="Check whether the external v2 attitude classifier is currently usable.")
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
        result = {
            "ok": False,
            "available": False,
            "state": "API_KEY_MISSING",
            "detail": "DASHSCOPE_API_KEY is not set in this PowerShell session.",
            "collection_blocked": False,
            "action": "Set the API key locally, then rerun this check. Collection may continue in degraded mode.",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        monitor = OpinionMonitorV2(concurrency=max(1, args.concurrency), retries=0, timeout=30)
        decision = monitor.classify("系统连通性测试文本。", "仅用于检查分类服务是否可用。")
        result = {
            "ok": True,
            "available": True,
            "state": "AVAILABLE",
            "model": monitor.model,
            "prompt_version": monitor.prompt_version,
            "probe_result": decision.to_dict(),
            "collection_blocked": False,
            "action": "Classifier is available. Degraded historical rows can now be backfilled without recrawling.",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ").strip()[:900]
        state = _classify_failure(detail)
        if state == "ACCOUNT_ARREARS":
            action = "Restore the DashScope account/billing status, then rerun this check. No crawler-code change can resolve an account arrears response."
        elif state == "QUOTA_OR_BALANCE":
            action = "Restore model quota/balance, then rerun this check."
        elif state == "RATE_LIMIT":
            action = "Wait for the provider rate limit to clear, then rerun this check."
        elif state == "NETWORK":
            action = "Check network/provider reachability, then rerun this check."
        else:
            action = "Inspect the provider error, then rerun this check. Collection can continue in degraded mode."
        result = {
            "ok": False,
            "available": False,
            "state": state,
            "detail": detail,
            "collection_blocked": False,
            "action": action,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
