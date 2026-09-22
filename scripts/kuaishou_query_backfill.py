"""Resumable, isolated Kuaishou query backfill.

Runs exactly one configured query and one search page per child process.  It is
intentionally separate from the formal monitoring root: all raw data, progress,
candidate decisions and coverage reports remain below ``--staging-root``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor.ingest import ingest_and_classify
from monitor.kuaishou_queries import build_kuaishou_query_plan
from monitor.orchestrator import load_config
from monitor.crawler_runner import find_content_jsonl, find_comment_jsonl
from pipeline.io_utils import read_jsonl, write_json
from run_single_platform import _kuaishou_cdp_preflight


STOP_MARKERS = ("captcha", "验证码", "need captcha", "verify required")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)


def _rows(paths: list[Path]) -> int:
    return sum(1 for path in paths for _ in read_jsonl(path))


def _tail_has_stop_marker(*paths: Path) -> str:
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace")[-8000:] for path in paths if path.exists()).lower()
    return next((marker for marker in STOP_MARKERS if marker in text), "")


def _terminate_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        proc.kill()


def _old_ids(root: Path) -> set[str]:
    path = root / "classified" / "classified_results.jsonl"
    values = set()
    for row in read_jsonl(path) if path.exists() else []:
        if row.get("record_type") == "comment":
            continue
        value = str(row.get("content_id") or row.get("url") or "").strip()
        if value:
            values.add(value)
    return values


def _creator_rows(root: Path) -> list[dict]:
    rows = []
    if not root.exists():
        return rows
    for path in root.rglob("classified_results.jsonl"):
        for row in read_jsonl(path):
            if row.get("record_type") != "comment":
                rows.append(row)
    return rows


def _run_page(cfg: dict, staging: Path, item: dict, page: int, timeout: int) -> dict:
    query = item["query"]
    page_dir = staging / "raw" / f"q_{item['index']:02d}" / f"page_{page:04d}"
    page_dir.mkdir(parents=True, exist_ok=True)
    stdout = page_dir / "stdout.log"
    stderr = page_dir / "stderr.log"
    cmd = [
        "uv", "run", "main.py", "--platform", "ks", "--lt", str(cfg.get("login_type", "qrcode")),
        "--type", "search", "--keywords", query, "--start", str(page),
        "--crawler_max_notes_count", "20", "--max_concurrency_num", "1",
        "--get_comment", "no", "--get_sub_comment", "no", "--save_data_option", "jsonl",
        "--save_data_path", str(page_dir), "--max_comments_count_singlenotes", str(cfg.get("max_comments_count_singlenotes", 100000)),
    ]
    started = time.monotonic()
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        kwargs = {"cwd": str(cfg["media_crawler_root"]), "stdout": out, "stderr": err, "text": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(cmd, **kwargs)
        try:
            rc = proc.wait(timeout=timeout)
            outcome = "ok" if rc == 0 else "failed"
        except subprocess.TimeoutExpired:
            _terminate_tree(proc)
            rc, outcome = 124, "timeout"
    content_files = find_content_jsonl(page_dir)
    comment_files = find_comment_jsonl(page_dir)
    marker = _tail_has_stop_marker(stdout, stderr)
    return {
        "page": page, "page_dir": str(page_dir), "return_code": rc, "outcome": "captcha" if marker else outcome,
        "stop_marker": marker, "elapsed_seconds": round(time.monotonic() - started, 2),
        "raw_content_rows": _rows(content_files), "raw_comment_rows": _rows(comment_files),
        "content_files": [str(x) for x in content_files], "comment_files": [str(x) for x in comment_files],
        "completed_at": _now(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--staging-root", required=True)
    ap.add_argument("--max-pages-per-query", type=int, default=10)
    ap.add_argument("--page-timeout-seconds", type=int, default=150)
    ap.add_argument("--creator-root", default="", help="Optional isolated creator-trial root; omit to disable creator comparison.")
    args = ap.parse_args()
    cfg = load_config(Path(args.config))
    staging = Path(args.staging_root)
    formal = Path(cfg["data_root"])
    if staging.resolve() == formal.resolve():
        raise SystemExit("staging root must not equal formal data root")
    plan = build_kuaishou_query_plan(cfg["kuaishou_query_catalog"])
    cdp_ok, cdp_reason = _kuaishou_cdp_preflight(int(cfg.get("cdp_debug_port", 9222)), 5.0)
    _save(staging / "preflight.json", {"at": _now(), "cdp_ok": cdp_ok, "cdp_reason": cdp_reason, "formal_root": str(formal), "staging_root": str(staging)})
    if not cdp_ok:
        print(json.dumps({"state": "CDP_UNAVAILABLE", "reason": cdp_reason}, ensure_ascii=False))
        return 2
    progress_path = staging / "query_progress.json"
    progress = _load(progress_path, {"version": 1, "queries": {}, "stopped": False})
    stopped = False
    for index, spec in enumerate(plan, start=1):
        key = f"{index:02d}:{spec['query']}"
        item = progress["queries"].setdefault(key, {"index": index, **spec, "pages": [], "next_page": 1, "state": "pending"})
        if item.get("state") in {"completed", "captcha"}:
            continue
        while int(item["next_page"]) <= args.max_pages_per_query:
            result = _run_page(cfg, staging, item, int(item["next_page"]), args.page_timeout_seconds)
            item["pages"].append(result)
            item["next_page"] += 1
            item["raw_content_rows"] = sum(x["raw_content_rows"] for x in item["pages"])
            item["raw_comment_rows"] = sum(x["raw_comment_rows"] for x in item["pages"])
            if result["outcome"] == "captcha":
                item["state"] = "captcha"; progress["stopped"] = True; progress["stop_reason"] = "captcha"; stopped = True
            elif result["outcome"] != "ok":
                item["state"] = result["outcome"]
            elif result["raw_content_rows"] == 0:
                item["state"] = "empty_page_end"
            if item["state"] != "pending":
                break
            _save(progress_path, progress)
        if item["state"] == "pending":
            item["state"] = "configured_page_limit_reached"
        _save(progress_path, progress)
        if stopped:
            break
    if stopped:
        print(json.dumps({"state": "CAPTCHA_STOP", "staging": str(staging)}, ensure_ascii=False)); return 3

    files = [*staging.glob("raw/q_*/*/*.jsonl")]
    summary = ingest_and_classify(
        "ks", files, staging / "state" / "seen_ids.json", staging / "classified" / "classified_results.jsonl",
        monitoring_start_time=str(cfg["monitoring_start_time"]), monitoring_end_time="",
        kuaishou_query_catalog=plan, enable_classification=False, enable_kuaishou_snapshots=False,
    )
    old = _old_ids(formal)
    relevant = [r for r in summary.pop("_classified_rows") if r.get("record_type") != "comment"]
    candidates = list(read_jsonl(staging / "classified" / "kuaishou_topic_candidates.jsonl"))
    candidate_ids = {str(x.get("content_id") or x.get("url") or "") for x in candidates}
    by_query = {spec["query"]: {"query": spec["query"], "query_type": spec["query_type"], "time_scope_candidate_count": 0} for spec in plan}
    for row in candidates:
        for query in row.get("search_queries") or []:
            if query in by_query:
                by_query[query]["time_scope_candidate_count"] += 1
    creator_rows = _creator_rows(Path(args.creator_root)) if args.creator_root else []
    creator_only = [
        {k: row.get(k) for k in ("content_id", "content", "author", "publish_time", "url")}
        for row in creator_rows
        if str(row.get("content_id") or row.get("url") or "") not in candidate_ids
    ]
    type_unique_new = {}
    for row in candidates:
        content_id = str(row.get("content_id") or row.get("url") or "")
        hits = row.get("query_hits") or []
        if content_id in old or len(hits) != 1:
            continue
        query_type = str(hits[0].get("query_type") or "unknown")
        type_unique_new[query_type] = type_unique_new.get(query_type, 0) + 1
    report = {
        "generated_at": _now(), "formal_root_read_only": str(formal), "staging_root": str(staging),
        "queries": list(progress["queries"].values()), "query_count": len(plan),
        "query_states": {x["state"]: sum(1 for y in progress["queries"].values() if y.get("state") == x["state"]) for x in {y.get("state") for y in progress["queries"].values()}},
        "per_query": list(by_query.values()),
        "raw_unique_content_candidates": len(candidate_ids),
        "relevant_count": len(relevant), "candidate_review_count": sum(1 for x in candidates if x.get("topic_relevance_status") == "candidate_review"),
        "new_relevant_count": sum(1 for x in relevant if str(x.get("content_id") or x.get("url") or "") not in old),
        "new_relevant": [{k: x.get(k) for k in ("content_id", "content", "author", "publish_time", "search_queries", "query_types")} for x in relevant if str(x.get("content_id") or x.get("url") or "") not in old],
        "old_not_rediscovered": sorted(old - candidate_ids),
        "creator_root_read_only": args.creator_root,
        "creator_only_discovery": creator_only,
        "unique_new_candidate_contribution_by_query_type": type_unique_new,
    }
    _save(staging / "coverage_comparison_report.json", report)
    print(json.dumps({"state": "COMPLETE", "report": str(staging / "coverage_comparison_report.json"), "relevant": len(relevant)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
