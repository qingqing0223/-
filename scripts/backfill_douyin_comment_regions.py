from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.ingest import (
    _canonical_public_region,
    _merge_regions_into_existing,
    _prepare_region_aliases,
)
from pipeline.normalizer import normalize_record


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _platform_root(cfg: dict) -> Path:
    base = Path(str(cfg["data_root"]))
    if base.name.endswith("_dy"):
        return base
    return base.parent / f"{base.name}_dy"


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                yield row


def _comment_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.jsonl")
        if "comment" in p.name.lower()
    )


def _region_stats(rows: list[dict]) -> tuple[int, Counter]:
    regions = Counter()
    count = 0
    for row in rows:
        if row.get("record_type") != "comment":
            continue
        region = _canonical_public_region(row.get("ip_location"))
        if region:
            count += 1
            regions[region] += 1
    return count, regions


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "One-time Douyin historical comment public-region backfill. "
            "It re-fetches only videos referenced by already classified comments, "
            "then enriches matching existing comment rows by comment ID. "
            "It does not reclassify attitude or publish raw text."
        )
    )
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.local.json"))
    ap.add_argument("--max-videos", type=int, default=0, help="0 means all videos with missing comment region")
    ap.add_argument("--max-comments-per-video", type=int, default=1000)
    ap.add_argument("--keep-raw", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_json(cfg_path)
    data_root = _platform_root(cfg)
    classified_path = data_root / "classified" / "classified_results.jsonl"
    if not classified_path.exists():
        print(json.dumps({
            "ok": False,
            "error": "classified_output_not_found",
            "path": str(classified_path),
        }, ensure_ascii=False, indent=2))
        return 2

    rows = list(_iter_jsonl(classified_path) or [])
    comment_rows = [r for r in rows if r.get("record_type") == "comment"]
    missing_rows = [
        r for r in comment_rows
        if not _canonical_public_region(r.get("ip_location"))
    ]
    missing_keys = {
        str(r.get("dedupe_key") or "").strip()
        for r in missing_rows
        if str(r.get("dedupe_key") or "").strip()
    }
    by_content: dict[str, set[str]] = defaultdict(set)
    for row in missing_rows:
        content_id = str(row.get("content_id") or "").strip()
        key = str(row.get("dedupe_key") or "").strip()
        if content_id and key:
            by_content[content_id].add(key)

    content_ids = sorted(by_content, key=lambda x: (-len(by_content[x]), x))
    if args.max_videos > 0:
        content_ids = content_ids[:args.max_videos]

    before_count, before_regions = _region_stats(rows)
    if not missing_keys:
        print(json.dumps({
            "ok": True,
            "platform": "dy",
            "data_root": str(data_root),
            "total_comment_records": len(comment_rows),
            "comment_region_records_before": before_count,
            "missing_comment_regions_before": 0,
            "updated": 0,
            "message": "All existing Douyin comment rows already have usable public-region labels.",
        }, ensure_ascii=False, indent=2))
        return 0

    if not content_ids:
        print(json.dumps({
            "ok": False,
            "error": "missing_comment_rows_have_no_content_id",
            "total_comment_records": len(comment_rows),
            "missing_comment_regions_before": len(missing_rows),
        }, ensure_ascii=False, indent=2))
        return 3

    media_root = Path(str(cfg.get("media_crawler_root") or r"E:\MediaCrawler_clean"))
    client_path = media_root / "media_platform" / "douyin" / "client.py"
    try:
        client_text = client_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        client_text = ""
    if "PROMOTION_WEEK_DY_COMMENT_REQUEST_PROFILE_V2" not in client_text:
        print(json.dumps({
            "ok": False,
            "error": "douyin_request_profile_v2_not_applied",
            "action": "Run the latest final student updater or region-backfill PowerShell wrapper first.",
            "client": str(client_path),
        }, ensure_ascii=False, indent=2))
        return 4

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_root = data_root / "region_backfill" / f"dy_{stamp}"
    work_root.mkdir(parents=True, exist_ok=True)
    stdout_log = work_root / "stdout.log"
    stderr_log = work_root / "stderr.log"

    region_by_key: dict[str, str] = {}
    attempted_videos = 0
    successful_videos = 0
    raw_comment_rows = 0
    failures = []

    max_comments_cap = max(50, min(int(args.max_comments_per_video), 5000))

    for index, content_id in enumerate(content_ids, 1):
        per_video_cap = min(
            max_comments_cap,
            max(100, min(5000, len(by_content[content_id]) * 4)),
        )
        cmd = [
            "uv", "run", "main.py",
            "--platform", "dy",
            "--lt", str(cfg.get("login_type", "qrcode")),
            "--type", "detail",
            "--specified_id", content_id,
            "--max_concurrency_num", "1",
            "--get_comment", "yes",
            "--get_sub_comment", "yes",
            "--save_data_option", "jsonl",
            "--save_data_path", str(work_root),
            "--max_comments_count_singlenotes", str(per_video_cap),
        ]
        attempted_videos += 1
        with stdout_log.open("a", encoding="utf-8") as out, stderr_log.open("a", encoding="utf-8") as err:
            out.write(
                f"\n[region-backfill] video={index}/{len(content_ids)} "
                f"content_id={content_id} target_missing={len(by_content[content_id])} "
                f"comment_cap={per_video_cap}\n"
            )
            proc = subprocess.run(
                cmd,
                cwd=media_root,
                stdout=out,
                stderr=err,
                text=True,
            )
        if proc.returncode == 0:
            successful_videos += 1
        else:
            failures.append({"content_id": content_id, "return_code": proc.returncode})

        # Re-scan collected comment files after each isolated video.  Matching
        # dedupe keys only are retained; no unrelated/new comment is written to
        # the classified production file by this backfill.
        for file in _comment_files(work_root):
            for raw in _iter_jsonl(file) or []:
                raw_comment_rows += 1
                prepared = _prepare_region_aliases(raw)
                rec = normalize_record(prepared, source_file=file.name, platform_hint="dy")
                if not rec or rec.get("record_type") != "comment":
                    continue
                key = str(rec.get("dedupe_key") or "").strip()
                if key not in missing_keys or key in region_by_key:
                    continue
                region = _canonical_public_region(rec.get("ip_location"))
                if region:
                    region_by_key[key] = region

        if len(region_by_key) >= len(missing_keys):
            break

    backup = classified_path.with_suffix(classified_path.suffix + ".before-dy-region-backfill")
    if region_by_key and not backup.exists():
        backup.write_bytes(classified_path.read_bytes())

    updated = _merge_regions_into_existing(classified_path, region_by_key)
    after_rows = list(_iter_jsonl(classified_path) or [])
    after_count, after_regions = _region_stats(after_rows)
    after_comments = [r for r in after_rows if r.get("record_type") == "comment"]
    missing_after = sum(
        1 for r in after_comments
        if not _canonical_public_region(r.get("ip_location"))
    )

    if not args.keep_raw:
        # Logs are enough for local troubleshooting; avoid retaining a second
        # raw comment corpus by default.
        for p in work_root.rglob("*.jsonl"):
            try:
                p.unlink()
            except Exception:
                pass

    result = {
        "ok": missing_after == 0,
        "platform": "dy",
        "data_root": str(data_root),
        "classified_output": str(classified_path),
        "backup": str(backup) if backup.exists() else "",
        "total_comment_records": len(after_comments),
        "comment_region_records_before": before_count,
        "comment_region_records_after": after_count,
        "missing_comment_regions_before": len(missing_rows),
        "missing_comment_regions_after": missing_after,
        "target_video_count": len(content_ids),
        "attempted_videos": attempted_videos,
        "successful_videos": successful_videos,
        "raw_comment_rows_scanned": raw_comment_rows,
        "matched_region_keys": len(region_by_key),
        "updated_existing_rows": updated,
        "region_coverage_after": round(after_count / len(after_comments), 4) if after_comments else 0.0,
        "regions_after": dict(after_regions.most_common()),
        "failures": failures[:10],
        "work_root": str(work_root),
        "note": (
            "Only existing classified Douyin comment rows are enriched by matching comment IDs. "
            "No new historical comments are added by this operation."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
