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


def _safe_text(element) -> str:
    try:
        return clean_text(element.window_text())
    except Exception:
        return ""


def _safe_type(element) -> str:
    try:
        return str(element.element_info.control_type or "")
    except Exception:
        return ""


def _visible(element) -> bool:
    try:
        return bool(element.is_visible())
    except Exception:
        return False


def _copy_text(text: str) -> None:
    import win32clipboard  # type: ignore
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _window_candidate(wrapper) -> tuple[int, dict]:
    try:
        class_name = str(wrapper.class_name() or "")
    except Exception:
        class_name = ""
    title = _safe_text(wrapper)
    try:
        descendants = wrapper.descendants()
    except Exception:
        descendants = []

    edits = [x for x in descendants if _safe_type(x) == "Edit" and _visible(x)]
    documents = [x for x in descendants if _safe_type(x) == "Document" and _visible(x)]

    texts: list[str] = []
    for item in descendants[:500]:
        text = _safe_text(item)
        if text and text not in texts:
            texts.append(text[:160])
        if len(texts) >= 60:
            break

    joined = " ".join(texts)
    is_wechatish = title in {"微信", "WeChat"} or "视频号" in joined or "Channels" in joined
    score = 0
    if class_name == "Chrome_WidgetWin_0":
        score += 2
    if title in {"微信", "WeChat"}:
        score += 3
    if edits:
        score += 4
    if documents:
        score += 4
    if "视频号" in joined or "Channels" in joined:
        score += 6
    if "搜索" in joined or "Search" in joined:
        score += 2

    return score, {
        "title": title,
        "class_name": class_name,
        "edit_count": len(edits),
        "document_count": len(documents),
        "sample_texts": texts[:20],
        "is_wechatish": is_wechatish,
    }


def _find_existing_channels_window(timeout: float = 1.0):
    """Attach to an already-open standalone Channels window, bypassing main-window UIA."""
    try:
        from pywinauto import Desktop  # type: ignore
    except Exception:
        return None, {}

    deadline = time.time() + max(0.2, timeout)
    best_spec = None
    best_meta: dict = {}
    best_score = -1

    while time.time() < deadline:
        try:
            desktop = Desktop(backend="uia")
            windows = desktop.windows(visible_only=True)
        except Exception:
            windows = []

        for wrapper in windows:
            try:
                score, meta = _window_candidate(wrapper)
                handle = int(wrapper.handle)
            except Exception:
                continue

            # Never attach to an arbitrary Chrome/Electron window.
            if not meta.get("is_wechatish"):
                continue
            if meta.get("class_name") != "Chrome_WidgetWin_0":
                continue
            if not meta.get("edit_count") or not meta.get("document_count"):
                continue

            if score > best_score:
                best_score = score
                best_meta = {**meta, "candidate_score": score, "handle": handle}
                try:
                    best_spec = desktop.window(handle=handle)
                except Exception:
                    best_spec = None

        if best_spec is not None and best_score >= 10:
            return best_spec, best_meta
        time.sleep(0.2)

    return None, best_meta


def _find_search_edit(window):
    try:
        edits = window.descendants(control_type="Edit")
    except Exception:
        edits = []
    visible = [x for x in edits if _visible(x)]
    for edit in visible:
        text = _safe_text(edit)
        if text in {"搜索", "Search"} or "搜索" in text or "Search" in text:
            return edit
    return visible[0] if visible else None


def _descendant_count(element) -> int:
    try:
        return len(element.descendants())
    except Exception:
        return 0


def _find_result_document(window, keyword: str, timeout: float):
    deadline = time.time() + max(1.0, timeout)
    fallback = None
    while time.time() < deadline:
        try:
            documents = [x for x in window.descendants(control_type="Document") if _visible(x)]
        except Exception:
            documents = []
        for doc in documents:
            title = _safe_text(doc)
            if title == f"{keyword}_搜索" or keyword in title:
                return doc
        if documents:
            fallback = max(documents, key=_descendant_count)
        time.sleep(0.25)
    return fallback


def _search_existing(window, keyword: str, load_delay: float):
    search_edit = _find_search_edit(window)
    if search_edit is None:
        return None, "search_edit_not_found"
    try:
        search_edit.click_input()
        search_edit.set_focus()
    except Exception:
        pass

    try:
        from pywinauto.keyboard import send_keys  # type: ignore
        _copy_text(keyword)
        send_keys("^a")
        time.sleep(0.1)
        send_keys("^v")
        time.sleep(0.1)
        send_keys("{ENTER}")
    except Exception as exc:
        return None, f"search_input_failed:{type(exc).__name__}:{exc}"

    document = _find_result_document(window, keyword, timeout=load_delay)
    if document is None:
        return None, "result_document_not_found"
    return document, ""


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
                text = _safe_text(child)
                if not text or text in COMMON_UI_LABELS:
                    continue
                if text not in texts:
                    texts.append(text)
            merged = "\n".join(texts).strip()
        except Exception:
            continue
        if 8 <= len(merged) <= 1200:
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
                text = _safe_text(child)
                if text and text not in COMMON_UI_LABELS and text != keyword and 4 <= len(text) <= 300:
                    texts.append(text)
            unique = list(dict.fromkeys(texts))[:max_results]
        except Exception:
            unique = []

    records = []
    for merged in unique:
        lines = [clean_text(x) for x in merged.splitlines() if clean_text(x)]
        title = lines[0] if lines else merged[:100]
        records.append(make_record(
            platform="wechat_channels",
            keyword=keyword,
            title=title[:200],
            content=merged[:4000],
            author="",
            url="",
            publish_time=parse_public_time(merged),
            record_type="video",
            raw_text=merged[:4000],
        ))
    return records


def _collect_document(document, keyword: str, max_results: int, scroll_pages: int) -> list[dict]:
    all_records: list[dict] = []
    seen_ids = set()
    for page_index in range(scroll_pages + 1):
        for row in _extract_groups(document, keyword, max_results):
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
    return all_records[:max_results]


def _collect_one(config: dict, keyword: str, Navigator, GlobalConfig) -> dict:
    load_delay = float(config.get("wechat_channels_load_delay_seconds", 5))
    max_results = int(config.get("wechat_channels_max_results_per_keyword", 20))
    scroll_pages = max(0, int(config.get("wechat_channels_scroll_pages", 2)))

    GlobalConfig.load_delay = load_delay
    GlobalConfig.is_maximize = True
    GlobalConfig.close_weixin = False

    # On some recent WeChat builds the main UI tree is hidden. If the user opens
    # Channels once manually, attach directly to that standalone window instead.
    existing, meta = _find_existing_channels_window(timeout=0.8)
    if existing is not None:
        document, error = _search_existing(existing, keyword, load_delay)
        if document is None:
            return {
                "status": "UI_NOT_READY",
                "records": [],
                "automation_mode": "preopened_channels_window",
                "window": meta,
                "error": error or "Channels search/result controls were not readable.",
            }
        records = _collect_document(document, keyword, max_results, scroll_pages)
        return {
            "status": "SUCCESS",
            "records": records,
            "visible_results": len(records),
            "automation_mode": "preopened_channels_window",
            "window": meta,
        }

    try:
        window = Navigator.search_channels(
            search_content=keyword,
            load_delay=load_delay,
            is_maximize=True,
            window_maximize=True,
            close_weixin=False,
        )
    except Exception as exc:
        message = f"{type(exc).__name__}:{exc}"
        if "UI树不可见" in message or type(exc).__name__ == "NotFoundError":
            return {
                "status": "CHANNELS_WINDOW_REQUIRED",
                "records": [],
                "automation_mode": "preopened_channels_window_required",
                "error": "微信主界面UI树不可见。请手动打开微信→视频号，保持视频号独立窗口可见，然后重新运行；后续关键词搜索将自动完成。",
            }
        raise

    if window is None:
        return {
            "status": "LOGIN_OR_UI_REQUIRED",
            "records": [],
            "error": "Channels search window did not become ready. Ensure WeChat is logged in and Channels can open normally.",
        }

    try:
        document = _find_result_document(window, keyword, load_delay)
        if document is None:
            return {
                "status": "UI_NOT_READY",
                "records": [],
                "automation_mode": "navigator",
                "error": "Channels search result document was not found; WeChat UI version may differ.",
            }
        records = _collect_document(document, keyword, max_results, scroll_pages)
        return {
            "status": "SUCCESS",
            "records": records,
            "visible_results": len(records),
            "automation_mode": "navigator",
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
    automation_mode = ""

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
                "automation_mode": automation_mode,
                "error": message,
            }

        automation_mode = str(result.get("automation_mode") or automation_mode)
        batch = result.get("records") or []
        all_records.extend(batch)
        per_keyword[keyword] = len(batch)
        if result.get("status") != "SUCCESS":
            return {
                "status": result.get("status"),
                "records": all_records,
                "per_keyword": per_keyword,
                "blocked_keyword": keyword,
                "automation_mode": automation_mode,
                "error": result.get("error", ""),
                "window": result.get("window") or {},
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
        "automation_mode": automation_mode,
    }


def collect(config: dict, keyword: str) -> dict:
    return collect_many(config, [keyword])
