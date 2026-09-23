"""Durable per-keyword search session; public navigation stays in mp_sogou."""
from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import quote

from .common import now_cn
from .mp_export import atomic_json, write_jsonl
from .mp_records import merge_records, stable_id, time_problem

FINISHED = {"SUCCESS", "NO_RESULTS"}


def collect_session(config: dict, keywords: list[str]) -> dict:
    from . import mp_sogou as dom
    from playwright.sync_api import sync_playwright

    root = Path(config.get("wechat_mp_work_root", "data/wechat_mp"))
    checkpoint_path = root / "in_progress/search_session_v4.json"
    fingerprint = stable_id(json.dumps({"keywords": keywords, "start": config.get("monitoring_start_time"), "end": config.get("monitoring_end_time"),
                                       "batch": config.get("wechat_mp_node_id"),
                                       "source": "sogou_public"}, ensure_ascii=False, sort_keys=True))
    saved = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    # A completed acceptance session remains reusable until its result is ingested.
    # Continuous polling explicitly permits a fresh round after ingestion.
    resume_completed = bool(config.get("wechat_mp_acceptance_mode"))
    if saved.get("fingerprint") == fingerprint and (not saved.get("complete") or resume_completed):
        session = saved
        print(f"[wechat_mp] 恢复采集进度: {session['run_id']}", flush=True)
    else:
        if saved:
            atomic_json(root / "search_sessions" / (saved["run_id"] + ".json"), saved)
        baseline_path = root / "state_v3.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["records"] if baseline_path.exists() else []
        session = {"version": 4, "fingerprint": fingerprint,
                   "run_id": now_cn().strftime("%Y%m%d_%H%M%S_%f"), "complete": False,
                   "records": [], "baseline": baseline, "canonical_index": 0,
                   "errors": [], "keyword_stats": {k: {
                       "status": "NOT_SEARCHED", "attempted": False, "requests": 0,
                       "pages": 0, "raw_hits": 0, "unique_hits": 0, "new_unique": 0,
                       "next_page": 1, "seen_ids": [], "page_hits": {}, "stop_reason": "",
                   } for k in keywords}}
    stats = session["keyword_stats"]
    max_pages = max(1, int(config.get("wechat_mp_max_pages", 1000)))
    max_results = max(1, int(config.get("wechat_mp_max_results_per_keyword", 100000)))
    exhausted = bool(config.get("wechat_mp_search_until_exhausted", False))
    manual_wait = int(config.get("wechat_mp_manual_verify_wait_seconds", config.get("wechat_manual_verify_wait_seconds", 600)))
    delay = max(1.0, float(config.get("wechat_mp_keyword_delay_seconds", 5)))
    current_keyword = None
    fresh_observations = 0

    def result(status: str) -> dict:
        public_stats = {k: {name: value for name, value in s.items() if name not in ("seen_ids", "page_hits")} for k, s in stats.items()}
        all_attempted = bool(stats) and all(s["attempted"] for s in stats.values())
        complete = all_attempted and all(s["status"] in FINISHED for s in stats.values())
        return {"status": status, "run_id": session["run_id"], "records": session["records"],
                "keyword_stats": public_stats, "keyword_coverage": {k: s["status"] for k, s in stats.items()},
                "per_keyword_status": {k: s["status"] for k, s in stats.items()},
                "per_keyword": {k: s["unique_hits"] for k, s in stats.items()},
                "per_keyword_pages": {k: s["pages"] for k, s in stats.items()},
                "all_keywords_executed": all_attempted, "search_acceptance_complete": complete,
                "canonical_attempted": session["canonical_index"],
                "canonical_resolved": sum(bool(r.get("canonical_url")) for r in session["records"]),
                 "blocked_stage": session.get("blocked_stage"), "errors": session["errors"],
                 "fresh_observations": fresh_observations}

    def save(status: str = "RUNNING") -> None:
        session["updated_at"] = now_cn().isoformat(timespec="seconds")
        atomic_json(checkpoint_path, session)  # All counters and candidates commit together.
        write_jsonl(root / "in_progress/search_contents.jsonl", session["records"])
        atomic_json(root / "in_progress/progress.json", {k: v for k, v in result(status).items() if k != "records"})

    def needs_verification(keyword: str | None) -> None:
        session["blocked_stage"] = "search" if keyword is not None else "public_article_link"
        if keyword is not None:
            stats[keyword].update(status="VERIFY_REQUIRED", stop_reason="awaiting_manual_verification")
        save("VERIFY_REQUIRED")

    if session["complete"]:
        return result("SUCCESS")
    save()
    try:
        with sync_playwright() as p:
            profile = root / "browser_profile"
            profile.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(str(profile),
                channel=config.get("wechat_mp_browser_channel", "chrome"), headless=False,
                viewport=None, args=["--start-maximized"])
            page = context.pages[0] if context.pages else context.new_page()
            for keyword in keywords:
                current_keyword = keyword
                s = stats[keyword]
                if s["status"] in FINISHED:
                    print(f"[wechat_mp] 已完成，保留结果: {keyword}", flush=True)
                    continue
                seen = set(s["seen_ids"])
                print(f"[wechat_mp] 搜索 {keyword}，从第{s['next_page']}页继续", flush=True)
                while s["next_page"] <= max_pages and s["unique_hits"] < max_results:
                    number = s["next_page"]
                    url = "https://weixin.sogou.com/weixin?type=2&query=" + quote(keyword) + f"&page={number}"
                    s.update(attempted=True, requests=s["requests"] + 1, status="ERROR", stop_reason="in_progress")
                    save()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(2000)
                    except Exception as exc:
                        s.update(status="ERROR", stop_reason="network_error")
                        session["errors"].append({"keyword": keyword, "page": number, "reason": type(exc).__name__})
                        save("PARTIAL")
                        break
                    if not dom._wait_for_manual_verify(page, manual_wait, lambda: needs_verification(keyword)):
                        needs_verification(keyword)
                        return result("VERIFY_REQUIRED")
                    session["blocked_stage"] = None
                    page_errors = []
                    batch = dom._extract_records(page, keyword, max_results - s["unique_hits"], page_errors)
                    fresh_observations += len(batch)
                    for r in batch:
                        r["search_page_url"] = url
                    raw_count = len(batch)
                    for selector in dom.RESULT_SELECTORS:
                        count = page.locator(selector).count()
                        if count:
                            raw_count = max(raw_count, count)
                            break
                    retrying_page = str(number) in s["page_hits"]
                    s["page_hits"][str(number)] = raw_count
                    s["pages"] = len(s["page_hits"])
                    s["raw_hits"] = sum(s["page_hits"].values())
                    previous_global = len(merge_records(session["baseline"], session["records"]))
                    session["records"] = merge_records(session["records"], batch)
                    s["new_unique"] += len(merge_records(session["baseline"], session["records"])) - previous_global
                    added = {r["content_id"] for r in batch} - seen
                    seen.update(r["content_id"] for r in batch)
                    s.update(unique_hits=len(seen), seen_ids=sorted(seen))
                    session["errors"].extend(page_errors)
                    # The page is durable before looking for the next page or URLs.
                    s["next_page"] = number + 1
                    if number == 1:
                        try:
                            dom._save_footer_sample(page, root / "debug" / f"footer_{keywords.index(keyword)+1}.html")
                        except Exception:
                            pass
                    if page_errors:
                        s.update(status="ERROR", stop_reason="card_parse_failed", next_page=number)
                    elif not batch:
                        body = dom.clean_text(page.locator("body").inner_text(timeout=2000))
                        if any(x in body for x in ("没有找到", "未找到", "无相关")):
                            s.update(status="SUCCESS" if s["unique_hits"] else "NO_RESULTS", stop_reason="natural_end")
                        else:
                            s.update(status="ERROR", stop_reason="empty_or_changed_dom", next_page=number)
                    elif not added and not retrying_page:
                        s.update(status="ERROR", stop_reason="repeated_page", next_page=number)
                    elif not page.locator("#sogou_next").count():
                        s.update(status="SUCCESS", stop_reason="natural_end")
                    elif not exhausted:
                        s.update(status="ERROR", stop_reason="single_page_limit")
                    else:
                        s.update(status="ERROR", stop_reason="in_progress")
                    save()
                    # Optional isolated node sink: publish durable page candidates
                    # before URL enrichment, later keywords, or a human captcha wait.
                    on_page = config.get("wechat_mp_on_page")
                    if callable(on_page):
                        on_page(batch, result("PARTIAL"))
                    print(f"[wechat_mp] {keyword}: {s['status']}, 页数={s['pages']}, 原始命中={s['raw_hits']}, 去重新增={s['new_unique']}", flush=True)
                    if s["stop_reason"] != "in_progress":
                        break
                    time.sleep(delay)
                if s["stop_reason"] == "in_progress":
                    s.update(status="ERROR", stop_reason="safety_cap")
                save()
                time.sleep(delay)
            current_keyword = None
            # URL enrichment cannot prevent later keywords from being searched.
            if config.get("wechat_mp_resolve_article_urls", True):
                for index in range(session["canonical_index"], len(session["records"])):
                    row = session["records"][index]
                    if not time_problem(row, config.get("monitoring_start_time", "2026-09-16T00:00:00+08:00"), config.get("monitoring_end_time")):
                        if not dom._resolve_public_url(context, row, manual_wait, lambda: needs_verification(None)):
                            needs_verification(None)
                            return result("VERIFY_REQUIRED")
                    session["canonical_index"] = index + 1
                    save()
            session["blocked_stage"] = None
            session["complete"] = result("SUCCESS")["search_acceptance_complete"]
            save("SUCCESS" if session["complete"] else "PARTIAL")
            context.close()
        return result("SUCCESS" if session["complete"] else "PARTIAL")
    except KeyboardInterrupt:
        if current_keyword is not None and stats[current_keyword]["status"] not in FINISHED | {"VERIFY_REQUIRED"}:
            stats[current_keyword].update(status="ERROR", stop_reason="interrupted")
        save("INTERRUPTED")
        print("[wechat_mp] 已保存进度。重跑同一命令继续，不丢弃已完成关键词。", flush=True)
        return result("INTERRUPTED")
    except Exception as exc:
        if current_keyword is not None and stats[current_keyword]["status"] not in FINISHED | {"VERIFY_REQUIRED"}:
            stats[current_keyword].update(status="ERROR", stop_reason=type(exc).__name__)
        session["errors"].append({"keyword": current_keyword, "reason": type(exc).__name__})
        save("COLLECTOR_ERROR")
        return result("COLLECTOR_ERROR")
