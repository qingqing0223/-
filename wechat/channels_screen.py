from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from .common import clean_text, make_record, parse_public_time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = ROOT / "config" / "wechat_channels_screen.local.json"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-flash"
WECHAT_TITLES = {"微信", "Weixin", "WeChat"}
WECHAT_CLASSES = {"Qt51514QWindowIcon", "Chrome_WidgetWin_0"}


def _load_calibration(config: dict) -> tuple[dict, Path]:
    path = Path(str(config.get("wechat_channels_screen_calibration") or DEFAULT_CALIBRATION))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise RuntimeError(
            "screen calibration missing; run: python .\\scripts\\calibrate_channels_screen.py"
        )
    return json.loads(path.read_text(encoding="utf-8-sig")), path


def _find_window(cal: dict) -> tuple[int, tuple[int, int, int, int], dict]:
    try:
        import win32gui  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"pywin32 unavailable: {type(exc).__name__}: {exc}") from exc

    expected_title = str(cal.get("window_title") or "")
    expected_class = str(cal.get("window_class") or "")
    candidates = []

    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = str(win32gui.GetWindowText(hwnd) or "")
            cls = str(win32gui.GetClassName(hwnd) or "")
            if title not in WECHAT_TITLES and cls not in WECHAT_CLASSES:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(0, right - left)
            height = max(0, bottom - top)
            if width < 500 or height < 400:
                return
            score = 0
            if expected_title and title == expected_title:
                score += 20
            if expected_class and cls == expected_class:
                score += 20
            if title in WECHAT_TITLES:
                score += 5
            if cls in WECHAT_CLASSES:
                score += 5
            candidates.append((score, width * height, hwnd, (left, top, right, bottom), title, cls))
        except Exception:
            return

    win32gui.EnumWindows(callback, None)
    if not candidates:
        raise RuntimeError("visible WeChat window not found")
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    score, _, hwnd, rect, title, cls = candidates[0]
    return hwnd, rect, {"title": title, "class_name": cls, "score": score, "handle": hwnd}


def _point(rect: tuple[int, int, int, int], ratio: dict) -> tuple[int, int]:
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    x = left + int(float(ratio["x"]) * width)
    y = top + int(float(ratio["y"]) * height)
    return x, y


def _results_bbox(rect: tuple[int, int, int, int], ratios: dict) -> tuple[int, int, int, int]:
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    l = left + int(float(ratios["left"]) * width)
    t = top + int(float(ratios["top"]) * height)
    r = left + int(float(ratios["right"]) * width)
    b = top + int(float(ratios["bottom"]) * height)
    if r <= l or b <= t:
        raise RuntimeError("invalid calibrated results rectangle")
    return l, t, r, b


def _bring_foreground(hwnd: int) -> None:
    import win32con  # type: ignore
    import win32gui  # type: ignore

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    try:
        win32gui.BringWindowToTop(hwnd)
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.4)


def _copy_text(text: str) -> None:
    import win32clipboard  # type: ignore

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _click(point: tuple[int, int]) -> None:
    import win32api  # type: ignore
    import win32con  # type: ignore

    win32api.SetCursorPos(point)
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _search(hwnd: int, search_point: tuple[int, int], keyword: str) -> None:
    try:
        from pywinauto.keyboard import send_keys  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"pywinauto keyboard unavailable: {type(exc).__name__}: {exc}") from exc

    _bring_foreground(hwnd)
    _click(search_point)
    _copy_text(keyword)
    send_keys("^a")
    time.sleep(0.15)
    send_keys("^v")
    time.sleep(0.15)
    send_keys("{ENTER}")


def _scroll_results(center: tuple[int, int], notches: int = 6) -> None:
    import win32api  # type: ignore
    import win32con  # type: ignore

    win32api.SetCursorPos(center)
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -120 * max(1, int(notches)), 0)


def _grab_image(bbox: tuple[int, int, int, int]):
    try:
        from PIL import ImageGrab  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Pillow missing; run: python -m pip install Pillow"
        ) from exc
    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    max_width = 1600
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * ratio))))
    return image


def _image_data_url(image) -> str:
    buf = BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + data


def _extract_json_text(text: str) -> dict:
    s = str(text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    try:
        value = json.loads(s)
        return value if isinstance(value, dict) else {"results": []}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", s, flags=re.S)
        if not match:
            raise RuntimeError("vision model did not return JSON")
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {"results": []}


def _vision_extract(image, keyword: str, config: dict) -> list[dict]:
    api_key = str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")

    model = str(config.get("wechat_channels_screen_model") or DEFAULT_MODEL)
    base_url = str(config.get("wechat_channels_screen_base_url") or DEFAULT_BASE_URL).rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    max_results = int(config.get("wechat_channels_max_results_per_keyword", 20))

    prompt = (
        "你正在读取微信视频号公开搜索结果区域的截图。搜索关键词是：" + keyword + "。\n"
        "只提取截图中当前可见的公开视频结果卡片，不要提取导航、搜索框、按钮或与结果无关的文字；"
        "不要推断截图中没有的信息。每条结果仅保留可见文本。\n"
        "严格只返回一个JSON对象，格式："
        '{"results":[{"title":"","author":"","publish_time_text":"","engagement_text":"","caption":""}]}。'
        f"最多返回{max_results}条；无法确定的字段填空字符串；没有结果时返回{{\"results\":[]}}。"
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 3000,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000].replace(api_key, "[REDACTED]")
        raise RuntimeError(f"vision API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"vision API network error: {exc.reason}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"vision API response envelope invalid: {type(exc).__name__}") from exc
    if isinstance(content, list):
        pieces = []
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                pieces.append(str(part["text"]))
        content = "\n".join(pieces)
    parsed = _extract_json_text(str(content or ""))
    results = parsed.get("results") or []
    if not isinstance(results, list):
        return []
    return [x for x in results if isinstance(x, dict)][:max_results]


def _rows_to_records(rows: list[dict], keyword: str) -> list[dict]:
    records = []
    for item in rows:
        title = clean_text(item.get("title"))
        caption = clean_text(item.get("caption"))
        author = clean_text(item.get("author"))
        time_text = clean_text(item.get("publish_time_text"))
        engagement = clean_text(item.get("engagement_text"))
        content = caption or title
        if not content:
            continue
        raw_parts = [x for x in (title, caption, author, time_text, engagement) if x]
        raw_text = " | ".join(raw_parts)
        row = make_record(
            platform="wechat_channels",
            keyword=keyword,
            title=title[:200] or content[:200],
            content=content[:4000],
            author=author[:300],
            url="",
            publish_time=parse_public_time(time_text),
            record_type="video",
            raw_text=raw_text[:4000],
        )
        row["analysis_basis"] = "visible_search_result_text_from_screen"
        row["screen_engagement_text"] = engagement
        records.append(row)
    return records


def collect_one(config: dict, keyword: str) -> dict:
    cal, cal_path = _load_calibration(config)
    hwnd, rect, window_meta = _find_window(cal)
    search_point = _point(rect, cal["search_point"])
    bbox = _results_bbox(rect, cal["results_rect"])
    center = ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)
    load_delay = max(2.0, float(config.get("wechat_channels_load_delay_seconds", 6)))
    scroll_pages = max(0, int(config.get("wechat_channels_screen_scroll_pages", 1)))
    max_results = max(1, int(config.get("wechat_channels_max_results_per_keyword", 20)))

    _search(hwnd, search_point, keyword)
    time.sleep(load_delay)

    all_records = []
    seen = set()
    page_counts = []
    for page_index in range(scroll_pages + 1):
        image = _grab_image(bbox)
        extracted = _vision_extract(image, keyword, config)
        records = _rows_to_records(extracted, keyword)
        page_counts.append(len(records))
        for row in records:
            cid = row.get("content_id")
            if cid and cid not in seen:
                seen.add(cid)
                all_records.append(row)
                if len(all_records) >= max_results:
                    break
        if len(all_records) >= max_results or page_index >= scroll_pages:
            break
        _bring_foreground(hwnd)
        _scroll_results(center)
        time.sleep(2.0)

    return {
        "status": "SUCCESS",
        "records": all_records[:max_results],
        "visible_results": len(all_records[:max_results]),
        "automation_mode": "screen_coordinate_qwen_vision",
        "calibration": str(cal_path),
        "window": window_meta,
        "page_counts": page_counts,
    }


def collect_many(config: dict, keywords: list[str]) -> dict:
    delay = max(1.0, float(config.get("wechat_channels_keyword_delay_seconds", 3)))
    all_records = []
    per_keyword = {}
    for keyword in keywords:
        try:
            result = collect_one(config, keyword)
        except Exception as exc:
            return {
                "status": "SCREEN_FALLBACK_ERROR",
                "records": all_records,
                "per_keyword": per_keyword,
                "blocked_keyword": keyword,
                "automation_mode": "screen_coordinate_qwen_vision",
                "error": f"{type(exc).__name__}:{exc}",
            }
        batch = result.get("records") or []
        all_records.extend(batch)
        per_keyword[keyword] = len(batch)
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
        "automation_mode": "screen_coordinate_qwen_vision",
    }
