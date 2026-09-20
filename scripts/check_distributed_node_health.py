from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu")
BAD_STATES = {"VERIFY_REQUIRED", "LOGIN_REQUIRED", "NETWORK_ERROR", "CRAWLER_FAILED", "RUNNER_ERROR"}


def _parse_time(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _latest_node_file(platform_root: Path) -> Path | None:
    files = [p for p in platform_root.glob("*.json") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _node_status(path: Path, now: datetime, max_age_seconds: int) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "path": str(path), "reason": f"invalid_json:{type(exc).__name__}:{exc}"}

    generated = _parse_time(payload.get("generated_at"))
    age = None
    if generated is not None:
        if generated.tzinfo is None and now.tzinfo is not None:
            generated = generated.replace(tzinfo=now.tzinfo)
        try:
            age = max(0.0, (now - generated.astimezone(now.tzinfo)).total_seconds())
        except Exception:
            age = None

    summary = payload.get("summary") or {}
    runtime = summary.get("runtime") or []
    last_runtime = runtime[-1] if runtime else {}
    totals = summary.get("totals") or {}
    diagnostics = payload.get("raw_diagnostics") or []
    diagnostics_available = any(bool(row.get("available")) for row in diagnostics if isinstance(row, dict))

    crawler_state = str(last_runtime.get("crawler_state") or "unknown")
    ingest_comments = bool(last_runtime.get("ingest_comments", False))
    comment_input_files = int(last_runtime.get("comment_input_file_count") or 0)
    comment_records = int(totals.get("comment_records") or 0)
    reply_records = int(totals.get("reply_comment_records") or 0)

    issues = []
    if generated is None:
        issues.append("missing_generated_at")
    elif age is not None and age > max_age_seconds:
        issues.append(f"stale>{max_age_seconds}s")
    if crawler_state in BAD_STATES:
        issues.append(f"crawler_state={crawler_state}")
    if not ingest_comments:
        issues.append("ingest_comments=false")
    if not diagnostics_available:
        issues.append("raw_diagnostics_unavailable")
    if comment_input_files == 0 and comment_records == 0 and crawler_state in {"SUCCESS", "SUCCESS_NO_COMMENTS"}:
        issues.append("no_comment_input_or_records")

    return {
        "ok": not issues,
        "path": str(path),
        "node_id": payload.get("node_id"),
        "platform": payload.get("platform"),
        "generated_at": payload.get("generated_at"),
        "age_seconds": round(age, 1) if age is not None else None,
        "crawler_state": crawler_state,
        "ingest_comments": ingest_comments,
        "comment_input_file_count": comment_input_files,
        "comment_records": comment_records,
        "reply_comment_records": reply_records,
        "comment_region_coverage_rate": totals.get("comment_region_coverage_rate", 0.0),
        "diagnostics_available": diagnostics_available,
        "issues": issues,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check whether all distributed platform nodes are alive on the five-minute monitoring cadence.")
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--date", default=datetime.now().astimezone().date().isoformat())
    ap.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS))
    ap.add_argument("--max-age-seconds", type=int, default=600, help="Two missed five-minute sync windows are considered stale by default.")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    node_root = repo_root / "results" / args.date / "nodes"
    required = [x.strip() for x in args.platforms.split(",") if x.strip()]
    now = datetime.now().astimezone()

    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "monitoring_cadence_seconds": 300,
        "stale_threshold_seconds": args.max_age_seconds,
        "date": args.date,
        "platforms": {},
        "healthy_platforms": 0,
        "unhealthy_platforms": 0,
        "missing_platforms": [],
    }

    for platform in required:
        platform_root = node_root / platform
        path = _latest_node_file(platform_root) if platform_root.exists() else None
        if path is None:
            row = {"ok": False, "platform": platform, "issues": ["missing_node_result"]}
            report["missing_platforms"].append(platform)
        else:
            row = _node_status(path, now, args.max_age_seconds)
        report["platforms"][platform] = row
        if row.get("ok"):
            report["healthy_platforms"] += 1
        else:
            report["unhealthy_platforms"] += 1

    report["ok"] = report["unhealthy_platforms"] == 0
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
