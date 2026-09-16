from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time

try:
    import win32api
    import win32con
    import win32gui
except Exception as exc:
    raise SystemExit(f"Missing pywin32 dependency: {type(exc).__name__}: {exc}")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "wechat_channels_screen.local.json"
WECHAT_TITLES = {"微信", "Weixin", "WeChat", "视频号", "Channels"}
WECHAT_CLASSES = {"Qt51514QWindowIcon", "Chrome_WidgetWin_0"}
VK_F8 = win32con.VK_F8
VK_ESC = win32con.VK_ESCAPE


def _find_wechat_window() -> tuple[int, tuple[int, int, int, int], str, str]:
    candidates: list[tuple[int, int, tuple[int, int, int, int], str, str, int]] = []

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
            if title in {"视频号", "Channels"}:
                score += 30
            if title in {"微信", "Weixin", "WeChat"}:
                score += 10
            if cls in WECHAT_CLASSES:
                score += 5
            candidates.append((score, area, (left, top, right, bottom), title, cls, hwnd))
        except Exception:
            return

    win32gui.EnumWindows(callback, None)
    if not candidates:
        raise SystemExit("没有找到可见的微信/视频号窗口。请先登录微信并手动打开视频号页面，再重试。")
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


def _key_down(vk: int) -> bool:
    return bool(win32api.GetAsyncKeyState(vk) & 0x8000)


def _wait_key_release(vk: int) -> None:
    while _key_down(vk):
        time.sleep(0.03)


def _capture_point(label: str, rect: tuple[int, int, int, int]) -> tuple[int, int]:
    print()
    print(label)
    print("把鼠标移动到目标位置，然后按 F8 记录；按 Esc 可退出。")
    print("无需回到 PowerShell，也不要点击鼠标。程序正在等待 F8 ...", flush=True)

    _wait_key_release(VK_F8)
    _wait_key_release(VK_ESC)
    while True:
        if _key_down(VK_ESC):
            raise SystemExit("已取消校准。")
        if _key_down(VK_F8):
            point = tuple(win32api.GetCursorPos())
            _wait_key_release(VK_F8)
            print(f"已记录位置: {point}", flush=True)
            left, top, right, bottom = rect
            if not (left <= point[0] <= right and top <= point[1] <= bottom):
                print("这个点不在检测到的微信/视频号窗口内，请重新移动鼠标并按 F8。", flush=True)
                continue
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass
            return point
        time.sleep(0.05)


def main() -> None:
    hwnd, rect, title, cls = _find_wechat_window()
    left, top, right, bottom = rect
    print("=== 视频号屏幕坐标校准 ===")
    print(f"检测窗口: {title!r} / {cls} / handle={hwnd}")
    print(f"窗口范围: left={left}, top={top}, right={right}, bottom={bottom}")
    print("请把微信/视频号窗口和这个 PowerShell 同时保持可见，或者直接切到视频号窗口。")
    print("本版不再要求按 Enter 倒计时：移动鼠标到目标位置后直接按 F8 即可记录。")

    search = _capture_point(
        "步骤1/3：把鼠标移到【视频号搜索输入框中间】，按 F8。",
        rect,
    )
    result_tl = _capture_point(
        "步骤2/3：把鼠标移到【搜索结果列表区域左上角】，按 F8。尽量避开左侧聊天栏。",
        rect,
    )
    result_br = _capture_point(
        "步骤3/3：把鼠标移到【搜索结果列表区域右下角】，按 F8。",
        rect,
    )

    search_ratio = _ratio(search, rect)
    tl_ratio = _ratio(result_tl, rect)
    br_ratio = _ratio(result_br, rect)
    if br_ratio["x"] <= tl_ratio["x"] or br_ratio["y"] <= tl_ratio["y"]:
        raise SystemExit("结果区域右下角必须位于左上角的右下方。请重新运行校准。")

    data = {
        "schema_version": 2,
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
    print("下一步可运行：python .\\scripts\\test_channels_screen_fallback.py --config .\\config\\monitoring.wechat.local.json")


if __name__ == "__main__":
    main()
