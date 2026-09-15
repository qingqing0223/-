from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow imports from repository root when executed as scripts/smoke_test.py.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.orchestrator import load_config, run_one_cycle


def main() -> int:
    cfg = load_config(ROOT / "config" / "monitoring.smoke.windows.json")
    result = run_one_cycle(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    ingests = result.get("ingest") or []
    no_content = any(i.get("skipped_reason") == "no_content_jsonl" for i in ingests)
    classified = sum(int(i.get("classified_records") or 0) for i in ingests)
    push = result.get("dashboard_push") or {}

    if no_content:
        print("\n[SMOKE TEST: FAIL] MediaCrawler exited but produced no content JSONL.")
        print("This is NOT treated as a successful crawl. If the browser is still on login/CAPTCHA/verification, complete that first and rerun.")
        print("Check the stdout_log/stderr_log paths printed above for the platform login/search details.")
        return 2

    if classified <= 0:
        print("\n[SMOKE TEST: INCONCLUSIVE] No new record reached v2 classification.")
        print("For this first smoke test we need at least one real record; use a keyword with known public results after login is confirmed.")
        return 3

    if not push.get("ok"):
        print("\n[SMOKE TEST: FAIL] v2 classification produced data, but dashboard push failed.")
        return 4

    print("\n[SMOKE TEST: PASS] MediaCrawler -> v2 -> Suqi /api/ingest completed with real records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
