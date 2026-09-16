from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        import uiautomator2 as u2
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "state": "UIAUTOMATOR2_MISSING",
            "detail": f"{type(exc).__name__}: {exc}",
            "install": "python -m pip install -U uiautomator2",
        }, ensure_ascii=False, indent=2))
        return 2

    try:
        d = u2.connect()
        info = d.info
        current = d.app_current()
        hierarchy = d.dump_hierarchy(compressed=False)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "state": "DEVICE_CONNECT_FAILED",
            "detail": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 3

    package = str(current.get("package") or "")
    activity = str(current.get("activity") or "")
    labels = ["视频号", "搜索", "微信", "朋友", "发现"]
    matched = [x for x in labels if x in hierarchy]
    result = {
        "ok": True,
        "state": "ANDROID_UI_TREE_VISIBLE" if hierarchy and "hierarchy" in hierarchy else "ANDROID_UI_TREE_EMPTY",
        "device": {
            "serial": getattr(d, "serial", ""),
            "screen_on": info.get("screenOn"),
            "display_width": info.get("displayWidth"),
            "display_height": info.get("displayHeight"),
            "sdk_int": info.get("sdkInt"),
        },
        "current_app": {
            "package": package,
            "activity": activity,
            "wechat_foreground": package == "com.tencent.mm",
        },
        "matched_ui_labels": matched,
        "hierarchy_chars": len(hierarchy or ""),
        "next": (
            "Open WeChat -> Channels -> search page and rerun this script."
            if package != "com.tencent.mm" or not any(x in matched for x in ("视频号", "搜索"))
            else "Android WeChat UI is readable; proceed to Channels automation prototype."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
