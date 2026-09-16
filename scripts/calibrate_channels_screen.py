from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time

try:
    import win32api
    import win32gui
except Exception as exc:
    raise SystemExit(f"Missing pywin32 dependency: {type(exc).__name__}: {exc}")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "wechat_channels_screen.local.json"
WECHAT_TITLES = {"微信", "Weixin", "WeChat"}
WECHAT_CLASSES = {"Qt51514QWindowIcon", "Chrome_WidgetWin_0"}


def _find_wechat_window() -> tuple[int, tuple[int, int, int, int], str, str]:
    candidates: list[tuple[int, int, tuple[int, int, int, int], str, str]] = []

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
            area = width * height
            if area < 150000:
                return
            score = 0
            if title in WECHAT_TITLES:
                score += 10
            if cls in WECHAT_CLASSES:
                score += 5
            candidates.append((score, area, (left, top, right, bottom), title, cls, hwnd))
        except Exception:
            return

    win32gui.EnumWindows(callback, None)
    if not candidates:
        raise SystemExit("没有找到可见的微信窗口。请先登录微信并手动打开视频号页面，再重试。")
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, rect, title, cls, hwnd = candidates[0]
    return hwnd, rect, title, cls


def _ratio(point: tuple[int, int], rect: tuple[int, int, int, int]) -> dict:
    x, y = point
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    return {
        "x": round((x - left) / width, 6),
        "y": round((y - top) / height, 6),
    }


def _capture_point(label: str, rect: tuple[int, int, int, int], seconds: int = 6) -> tuple[int, int]:
    print()
    print(label)
    input("按 Enter 开始倒计时；随后把鼠标移动到目标位置并保持不动。")
    for remaining in range(seconds, 0, -1):
        print(f"  {remaining} 秒后记录鼠标位置...", end="\r", flush=True)
        time.sleep(1)
    point = tuple(win32api.GetCursorPos())
    print(f"  已记录位置: {point}                    ")
    left, top, right, bottom = rect
    if not (left <= point[0] <= right and top <= point[1] <= bottom):
        raise SystemExit("记录点不在微信窗口内。请重新运行校准。")
    return point


def main() -> None:
    hwnd, rect, title, cls = _find_wechat_window()
    left, top, right, bottom = rect
    print("=== 视频号屏幕坐标校准 ===")
    print(f"窗口: {title!r} / {cls} / handle={hwnd}")
    print(f"窗口范围: left={left}, top={top}, right={right}, bottom={bottom}")
    print("请保持视频号页面已经打开。这个校准只保存窗口内相对位置，不保存聊天内容。")

    search = _capture_point(
        "步骤1/3：把鼠标移动到【视频号搜索输入框的中间位置】。",
        rect,
    )
    result_tl = _capture_point(
        "步骤2/3：把鼠标移动到【搜索结果列表区域的左上角】。尽量避开左侧聊天栏。",
        rect,
    )
    result_br = _capture_point(
        "步骤3/3：把鼠标移动到【搜索结果列表区域的右下角】。",
        rect,
    )

    search_ratio = _ratio(search, rect)
    tl_ratio = _ratio(result_tl, rect)
    br_ratio = _ratio(result_br, rect)
    if br_ratio["x"] <= tl_ratio["x"] or br_ratio["y"] <= tl_ratio["y"]:
        raise SystemExit("结果区域右下角必须位于左上角的右下方。请重新运行校准。")

    data = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window_title": title,
        "window_class": cls,
        "reference_window_size": {
            "width": right - left,
            "height": bottom - top,
        },
        "search_point": search_ratio,
        "results_rect": {
            "left": tl_ratio["x"],
            "top": tl_ratio["y"],
            "right": br_ratio["x"],
            "bottom": br_ratio["y"],
        },
        "notes": "Local-only Channels screen calibration; do not commit this file.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"校准完成：{OUT}")
    print("下一步可运行：python .\\scripts\\test_channels_screen_fallback.py")


if __name__ == "__main__":
    main()
