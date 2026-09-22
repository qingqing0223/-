from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo


BJ = ZoneInfo("Asia/Shanghai")
CAPTCHA_MARKERS = ("captcha", "need captcha", "验证码", "安全验证", "verify_required")


def read_targets(delivery_dir: Path | None = None, targets_file: Path | None = None, expected_count: int = 14) -> list[dict]:
    if targets_file:
        rows = json.loads(targets_file.read_text(encoding="utf-8"))
    else:
        source = delivery_dir / "prepared_delivery_tables.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload.get("table1") or []
    targets, seen = [], set()
    for row in rows:
        cid = str(row.get("content_id") or "").strip()
        if cid and cid not in seen:
            seen.add(cid)
            targets.append({"content_id": cid, "url": row.get("original_url"), "title": row.get("title")})
    if expected_count > 0 and len(targets) != expected_count:
        raise RuntimeError(f"Expected exactly {expected_count} target contents, got {len(targets)}")
    return targets


def directory_fingerprint(root: Path) -> dict:
    rows = []
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: str(p).lower()):
        stat = path.stat()
        rows.append([str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns])
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"root": str(root), "file_count": len(rows), "sha256_metadata": digest}


async def cdp_handshake(port: int, timeout: float) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
        version = json.loads(response.read().decode("utf-8"))
    ws = str(version.get("webSocketDebuggerUrl") or "").strip()
    if not ws:
        raise RuntimeError("CDP /json/version missing webSocketDebuggerUrl")
    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    browser = None
    try:
        browser = await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(ws, timeout=int(timeout * 1000)), timeout=timeout
        )
        contexts = len(browser.contexts)
        pages = sum(len(c.pages) for c in browser.contexts)
        return {"ok": True, "browser": version.get("Browser"), "webSocketDebuggerUrl": ws, "contexts": contexts, "pages": pages}
    finally:
        # Disconnect this Playwright client only. External Chrome stays alive.
        await playwright.stop()


def terminate_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
    else:
        try:
            os.killpg(proc.pid, 15)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def iter_jsonl(root: Path, name_contains: str):
    for path in root.rglob("*.jsonl"):
        if name_contains not in path.name.lower():
            continue
        with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    yield row


def parse_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdigit():
            number = int(value)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=BJ)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(BJ)
    except Exception:
        return None


def normalize_and_filter(output: Path, targets: list[dict], start: datetime, end: datetime) -> dict:
    target_ids = {row["content_id"] for row in targets}
    raw, accepted = [], {}
    for row in iter_jsonl(output / "runs", "comment"):
        raw.append(row)
        cid = str(row.get("video_id") or row.get("content_id") or row.get("photo_id") or "").strip()
        comment_id = str(row.get("comment_id") or row.get("commentId") or "").strip()
        published = parse_time(row.get("create_time") or row.get("timestamp") or row.get("publish_time"))
        if cid not in target_ids or not comment_id or published is None or not (start <= published < end):
            continue
        parent = str(row.get("parent_comment_id") or "").strip()
        root = str(row.get("root_comment_id") or "").strip()
        accepted.setdefault(comment_id, {
            "corresponding_content_id": cid,
            "comment_id": comment_id,
            "platform_name": "快手",
            "comment_user_id": row.get("creator_hash"),
            "comment_user_ip_region": row.get("ip_location") or None,
            "comment_text": row.get("content"),
            "comment_publish_time": published.isoformat(timespec="seconds"),
            "is_valid_comment": "是",
            "comment_level": 2 if parent or root else 1,
            "parent_comment_id": parent or None,
            "root_comment_id": root or (comment_id if not parent else None),
            "data_collection_time": datetime.now(BJ).isoformat(timespec="seconds"),
            "raw": row,
        })

    raw_path = output / "raw_comments_all.jsonl"
    raw_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw), encoding="utf-8")
    table2 = list(accepted.values())
    (output / "table2_comment_backfill.jsonl").write_text(
        "".join(json.dumps({k: v for k, v in r.items() if k != "raw"}, ensure_ascii=False) + "\n" for r in table2), encoding="utf-8"
    )

    table4 = []
    collected_at = datetime.now(BJ).isoformat(timespec="seconds")
    for row in table2:
        src = row["raw"]
        like = next((src.get(k) for k in ("like_count", "liked_count", "likeCount", "likedCount") if src.get(k) not in (None, "")), None)
        reply = next((src.get(k) for k in ("reply_count", "sub_comment_count", "subCommentCount") if src.get(k) not in (None, "", "0", 0)), None)
        if like is None and reply is None:
            continue
        table4.append({
            "corresponding_content_id": row["corresponding_content_id"], "comment_id": row["comment_id"], "platform_name": "快手",
            "statistics_time": collected_at, "comment_reply_count": reply, "comment_like_count": like,
        })
    (output / "table4_comment_interaction_backfill.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in table4), encoding="utf-8"
    )
    def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    write_csv(output / "table2_comment_backfill.csv", table2, [
        "corresponding_content_id", "comment_id", "platform_name", "comment_user_id",
        "comment_user_ip_region", "comment_text", "comment_publish_time", "is_valid_comment",
        "comment_level", "parent_comment_id", "root_comment_id", "data_collection_time",
    ])
    write_csv(output / "table4_comment_interaction_backfill.csv", table4, [
        "corresponding_content_id", "comment_id", "platform_name", "statistics_time",
        "comment_reply_count", "comment_like_count",
    ])
    roots = sum(1 for r in table2 if r["comment_level"] == 1)
    replies = len(table2) - roots
    regions = sum(1 for r in table2 if r["comment_user_ip_region"])
    return {"raw_comment_count": len(raw), "in_window_comment_count": len(table2), "root_comment_count": roots,
            "nested_reply_count": replies, "ip_region_count": regions, "ip_region_rate": regions / len(table2) if table2 else 0,
            "table4_usable_records": len(table4)}


def merge_candidate_files(previous: Path, current: Path) -> dict:
    def load(path: Path) -> list[dict]:
        rows = []
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def dedupe(rows: list[dict]) -> list[dict]:
        result, seen = [], set()
        for row in rows:
            key = str(row.get("comment_id") or "").strip()
            if key and key not in seen:
                seen.add(key)
                result.append(row)
        return result

    previous_table2 = previous / "final_merged_table2_comment_candidates.jsonl"
    if not previous_table2.exists():
        previous_table2 = previous / "table2_comment_backfill.jsonl"
    previous_table4 = previous / "final_merged_table4_comment_interactions.jsonl"
    if not previous_table4.exists():
        previous_table4 = previous / "table4_comment_interaction_backfill.jsonl"
    table2 = dedupe(load(previous_table2) + load(current / "table2_comment_backfill.jsonl"))
    table4 = dedupe(load(previous_table4) + load(current / "table4_comment_interaction_backfill.jsonl"))
    (current / "final_merged_table2_comment_candidates.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in table2), encoding="utf-8")
    (current / "final_merged_table4_comment_interactions.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in table4), encoding="utf-8")
    def csv_out(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows)
    csv_out(current / "final_merged_table2_comment_candidates.csv", table2, [
        "corresponding_content_id", "comment_id", "platform_name", "comment_user_id",
        "comment_user_ip_region", "comment_text", "comment_publish_time", "is_valid_comment",
        "comment_level", "parent_comment_id", "root_comment_id", "data_collection_time",
    ])
    csv_out(current / "final_merged_table4_comment_interactions.csv", table4, [
        "corresponding_content_id", "comment_id", "platform_name", "statistics_time",
        "comment_reply_count", "comment_like_count",
    ])
    return {"merged_table2_records": len(table2), "merged_table4_records": len(table4)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fixed-target Kuaishou comment backfill for 14 confirmed relevant contents")
    ap.add_argument("--delivery-dir")
    ap.add_argument("--targets-file")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--formal-root", required=True)
    ap.add_argument("--media-crawler-root", required=True)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--candidate-timeout", type=int, default=90)
    ap.add_argument("--max-comments", type=int, default=1000)
    ap.add_argument("--expected-target-count", type=int, default=14)
    ap.add_argument("--network-retries", type=int, default=0)
    ap.add_argument("--merge-with")
    args = ap.parse_args()

    delivery = Path(args.delivery_dir) if args.delivery_dir else None
    targets_file = Path(args.targets_file) if args.targets_file else None
    if not delivery and not targets_file:
        raise RuntimeError("Either --delivery-dir or --targets-file is required")
    output, formal, media = map(Path, (args.output_dir, args.formal_root, args.media_crawler_root))
    if output.resolve() == formal.resolve() or formal.resolve() in output.resolve().parents:
        raise RuntimeError("Output must be isolated from the formal root")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    targets = read_targets(delivery, targets_file, args.expected_target_count)
    (output / "target_contents_14.json").write_text(json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before = directory_fingerprint(formal)
    try:
        handshake = asyncio.run(cdp_handshake(args.port, 5.0))
    except Exception as exc:
        (output / "cdp_preflight.json").write_text(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"CDP_UNAVAILABLE: {exc}", file=sys.stderr)
        return 125
    (output / "cdp_preflight.json").write_text(json.dumps(handshake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    runs = output / "runs"
    runs.mkdir()
    results, captcha = [], False
    for index, target in enumerate(targets, 1):
        cid = target["content_id"]
        run_dir = runs / f"{index:02d}_{cid}"
        run_dir.mkdir()
        started = time.monotonic()
        status, rc, attempts, failure_reason = "failed", None, [], ""
        for attempt_no in range(1, 2 + max(0, args.network_retries)):
            attempt_dir = run_dir / f"attempt_{attempt_no}"
            attempt_dir.mkdir()
            stdout, stderr = attempt_dir / "stdout.log", attempt_dir / "stderr.log"
            cmd = ["uv", "run", "main.py", "--platform", "ks", "--lt", "qrcode", "--type", "detail",
                   "--specified_id", cid, "--max_concurrency_num", "1", "--get_comment", "yes", "--get_sub_comment", "yes",
                   "--save_data_option", "jsonl", "--save_data_path", str(attempt_dir),
                   "--max_comments_count_singlenotes", str(args.max_comments)]
            with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
                kwargs = {"cwd": media, "stdout": out, "stderr": err, "text": True}
                if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else: kwargs["start_new_session"] = True
                proc = subprocess.Popen(cmd, **kwargs)
                attempt_status = "completed"
                try:
                    rc = proc.wait(timeout=args.candidate_timeout)
                    if rc != 0: attempt_status = "failed"
                except subprocess.TimeoutExpired:
                    terminate_tree(proc); rc, attempt_status = 124, "timeout"
            text = stdout.read_text(encoding="utf-8", errors="replace") + "\n" + stderr.read_text(encoding="utf-8", errors="replace")
            lower = text.lower()
            captcha = any(marker in lower for marker in CAPTCHA_MARKERS)
            network_error = "err_connection_closed" in lower or "err_network_changed" in lower
            failure_reason = "captcha" if captcha else ("network_error" if network_error else ("timeout" if rc == 124 else ("" if rc == 0 else "crawler_failed")))
            attempts.append({"attempt": attempt_no, "return_code": rc, "status": attempt_status, "failure_reason": failure_reason})
            status = "captcha_detected" if captcha else attempt_status
            if rc == 0 or captcha or not network_error or attempt_no > args.network_retries:
                break
        comments = sum(1 for _ in iter_jsonl(run_dir, "comment"))
        results.append({"content_id": cid, "status": status, "return_code": rc, "failure_reason": failure_reason,
                        "attempts": attempts, "duration_seconds": round(time.monotonic()-started, 2), "raw_comment_rows": comments})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        if captcha:
            results[-1]["status"] = "captcha_detected"
            break

    start = datetime.fromisoformat("2026-09-21T09:00:00+08:00")
    end = datetime.fromisoformat("2026-09-21T17:00:00+08:00")
    stats = normalize_and_filter(output, targets, start, end)
    after = directory_fingerprint(formal)
    report = {"target_count": len(targets), "attempted_count": len(results),
              "contents_with_raw_comments": sum(1 for r in results if r["raw_comment_rows"] > 0),
              "captcha_detected": captcha, "per_content": results, **stats,
              "formal_root_before": before, "formal_root_after": after,
              "formal_root_unchanged": before == after}
    if args.merge_with:
        report.update(merge_candidate_files(Path(args.merge_with), output))
    failures = [r for r in results if r["status"] != "completed"]
    if len(results) < len(targets):
        attempted_ids = {r["content_id"] for r in results}
        failures.extend({"content_id": t["content_id"], "status": "not_attempted_after_stop", "return_code": None}
                        for t in targets if t["content_id"] not in attempted_ids)
    (output / "failed_contents.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "backfill_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 126 if captcha else 0


if __name__ == "__main__":
    raise SystemExit(main())
