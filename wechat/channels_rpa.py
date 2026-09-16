from __future__ import annotations

from pathlib import Path
import sys
import time

from .common import clean_text, make_record, parse_public_time

COMMON_UI_LABELS = {
    "搜索", "视频号", "推荐", "朋友", "关注", "热点", "附近", "直播",
    "发现", "首页", "返回", "更多", "取消", "关闭",
}


def _load_pyweixin(config: dict):
    root = Path(config.get("pywechat_root") or r"E:\pywechat_rpa")
    src = root / "src"
    if not src.exists():
        raise RuntimeError(f"pywechat source not found: {src}")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from pyweixin import Navigator, GlobalConfig  # type: ignore
    return Navigator, GlobalConfig


def _safe_window_text(element) -> str:
    try:
        return clean_text(element.window_text())
    except Exception:
        return ""


def _extract_groups(document, keyword: str, max_results: int) -> list[dict]:
    candidates: list[str] = []
    try:
        groups = document.descendants(control_type="Group")
    except Exception:
        groups = []

    for group in groups:
        try:
            texts = []
            for child in group.descendants(control_type="Text"):
                text = _safe_window_text(child)
                if not text or text in COMMON_UI_LABELS:
                    continue
                if text not in texts:
                    texts.append(text)
            merged = "\n".join(texts).strip()
        except Exception:
            continue
        if len(merged) < 8 or len(merged) > 1200:
            continue
        candidates.append(merged)

    unique: list[str] = []
    for text in sorted(set(candidates), key=len):
        if any(text == x or text in x or x in text for x in unique):
            continue
        unique.append(text)
        if len(unique) >= max_results:
            break

    if not unique:
        try:
            texts = []
            for child in document.descendants(control_type="Text"):
                text = _safe_window_text(child)
                if text and text not in COMMON_UI_LABELS and text != keyword and 4 <= len(text) <= 300:
                    texts.append(text)
            unique = list(dict.fromkeys(texts))[:max_results]
        except Exception:
            unique = []

    records = []
    for merged in unique:
        lines = [clean_text(x) for x in merged.splitlines() if clean_text(x)]
        title = lines[0] if lines else merged[:100]
        publish_time = parse_public_time(merged)
        records.append(
            make_record(
                platform="wechat_channels",
                keyword=keyword,
                title=title[:200],
                content=merged[:4000],
                author="",
                url="",
                publish_time=publish_time,
                record_type="video",
                raw_text=merged[:4000],
            )
        )
    return records


def _collect_one(config: dict, keyword: str, Navigator, GlobalConfig) -> dict:
    load_delay = float(config.get("wechat_channels_load_delay_seconds", 5))
    max_results = int(config.get("wechat_channels_max_results_per_keyword", 20))
    scroll_pages = max(0, int(config.get("wechat_channels_scroll_pages", 2)))

    GlobalConfig.load_delay = load_delay
    GlobalConfig.is_maximize = True
    GlobalConfig.close_weixin = False

    window = Navigator.search_channels(
        search_content=keyword,
        load_delay=load_delay,
        is_maximize=True,
        window_maximize=True,
        close_weixin=False,
    )
    if window is None:
        return {
            "status": "LOGIN_OR_UI_REQUIRED",
            "records": [],
            "error": "Channels search window did not become ready. Ensure WeChat is logged in and Channels can open normally.",
        }

    try:
        document_spec = window.child_window(control_type="Document", title=f"{keyword}_搜索")
        if not document_spec.exists(timeout=load_delay, retry_interval=0.2):
            return {
                "status": "UI_NOT_READY",
                "records": [],
                "error": "Channels search result document was not found; WeChat UI version may differ.",
            }

        document = document_spec.wrapper_object()
        all_records: list[dict] = []
        seen_ids = set()

        for page_index in range(scroll_pages + 1):
            records = _extract_groups(document, keyword, max_results=max_results)
            for row in records:
                cid = row.get("content_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_records.append(row)
            if len(all_records) >= max_results or page_index >= scroll_pages:
                break
            try:
                document.set_focus()
                document.type_keys("{PGDN}")
            except Exception:
                try:
                    from pywinauto.keyboard import send_keys  # type: ignore
                    send_keys("{PGDN}")
                except Exception:
                    break
            time.sleep(1.5)

        return {
            "status": "SUCCESS",
            "records": all_records[:max_results],
            "visible_results": len(all_records[:max_results]),
        }
    finally:
        try:
            window.close()
        except Exception:
            pass


def collect_many(config: dict, keywords: list[str]) -> dict:
    try:
        Navigator, GlobalConfig = _load_pyweixin(config)
    except Exception as exc:
        return {
            "status": "SETUP_REQUIRED",
            "records": [],
            "error": f"pyweixin_not_available:{type(exc).__name__}:{exc}",
        }

    delay = max(1.0, float(config.get("wechat_channels_keyword_delay_seconds", 3)))
    all_records: list[dict] = []
    per_keyword: dict[str, int] = {}

    for keyword in keywords:
        try:
            result = _collect_one(config, keyword, Navigator, GlobalConfig)
        except Exception as exc:
            message = f"{type(exc).__name__}:{exc}"
            lowered = message.lower()
            state = "LOGIN_REQUIRED" if "login" in lowered or "登录" in message else "COLLECTOR_ERROR"
            return {
                "status": state,
                "records": all_records,
                "per_keyword": per_keyword,
                "blocked_keyword": keyword,
                "error": message,
            }

        batch = result.get("records") or []
        all_records.extend(batch)
        per_keyword[keyword] = len(batch)
        if result.get("status") != "SUCCESS":
            return {
                "status": result.get("status"),
                "records": all_records,
                "per_keyword": per_keyword,
                "blocked_keyword": keyword,
                "error": result.get("error", ""),
            }
        time.sleep(delay)

    deduped = []
    seen = set()
    for row in all_records:
        key = row.get("content_id") or row.get("content")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return {
        "status": "SUCCESS",
        "records": deduped,
        "per_keyword": per_keyword,
        "visible_results": len(deduped),
    }


def collect(config: dict, keyword: str) -> dict:
    return collect_many(config, [keyword])
