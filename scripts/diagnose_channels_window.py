from __future__ import annotations

import json

try:
    import win32gui
except Exception as exc:
    raise SystemExit(f"Missing dependency win32gui: {type(exc).__name__}: {exc}")

try:
    from pywinauto import Desktop
except Exception as exc:
    raise SystemExit(f"Missing dependency pywinauto: {type(exc).__name__}: {exc}")


def safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def probe_pywinauto() -> dict:
    desktop = Desktop(backend="uia")
    rows = []

    for wrapper in desktop.windows(visible_only=True):
        class_name = safe(lambda w=wrapper: w.class_name(), "") or ""
        title = safe(lambda w=wrapper: w.window_text(), "") or ""
        if class_name not in {"Chrome_WidgetWin_0", "Qt51514QWindowIcon"} and title not in {"微信", "WeChat", "Weixin"}:
            continue

        descendants = safe(lambda w=wrapper: w.descendants(), []) or []
        edits = [x for x in descendants if safe(lambda i=x: i.element_info.control_type, "") == "Edit"]
        documents = [x for x in descendants if safe(lambda i=x: i.element_info.control_type, "") == "Document"]

        texts = []
        for item in descendants[:500]:
            text = str(safe(lambda i=item: i.window_text(), "") or "").strip()
            if text and text not in texts:
                texts.append(text[:160])
            if len(texts) >= 40:
                break

        joined = " ".join(texts)
        is_wechatish = title in {"微信", "WeChat", "Weixin"} or "视频号" in joined or "Channels" in joined
        score = 0
        if class_name in {"Chrome_WidgetWin_0", "Qt51514QWindowIcon"}:
            score += 2
        if title in {"微信", "WeChat", "Weixin"}:
            score += 3
        if edits:
            score += 4
        if documents:
            score += 4
        if "视频号" in joined or "Channels" in joined:
            score += 6
        if "搜索" in joined or "Search" in joined:
            score += 2

        rows.append({
            "handle": int(safe(lambda w=wrapper: w.handle, 0) or 0),
            "title": title,
            "class_name": class_name,
            "visible": bool(safe(lambda w=wrapper: w.is_visible(), False)),
            "descendant_count": len(descendants),
            "edit_count": len(edits),
            "document_count": len(documents),
            "is_wechatish": is_wechatish,
            "sample_texts": texts,
            "candidate_score": score,
        })

    rows.sort(key=lambda x: x["candidate_score"], reverse=True)
    good = [
        r for r in rows
        if r["is_wechatish"]
        and r["edit_count"] > 0
        and r["document_count"] > 0
        and r["candidate_score"] >= 10
    ]
    return {
        "diagnosis": "CHANNELS_PYWINAUTO_TREE_VISIBLE" if good else "CHANNELS_PYWINAUTO_TREE_NOT_VISIBLE",
        "channels_candidates": good[:5],
        "all_candidates": rows[:10],
    }


def _uia_control_row(ctrl) -> dict:
    return {
        "name": str(safe(lambda: ctrl.Name, "") or ""),
        "class_name": str(safe(lambda: ctrl.ClassName, "") or ""),
        "automation_id": str(safe(lambda: ctrl.AutomationId, "") or ""),
        "control_type": str(safe(lambda: ctrl.ControlTypeName, "") or ""),
    }


def _walk_uia(ctrl, depth: int = 0, max_depth: int = 5, max_nodes: int = 300, rows=None):
    if rows is None:
        rows = []
    if ctrl is None or depth > max_depth or len(rows) >= max_nodes:
        return rows
    rows.append({"depth": depth, **_uia_control_row(ctrl)})
    if depth >= max_depth:
        return rows
    children = safe(lambda: ctrl.GetChildren(), []) or []
    for child in children:
        if len(rows) >= max_nodes:
            break
        _walk_uia(child, depth + 1, max_depth, max_nodes, rows)
    return rows


def probe_uiautomation() -> dict:
    try:
        import uiautomation as uia  # type: ignore
    except Exception as exc:
        return {
            "diagnosis": "UIAUTOMATION_PACKAGE_MISSING",
            "detail": f"{type(exc).__name__}: {exc}",
            "install_command": "python -m pip install uiautomation",
        }

    hwnd = 0
    matched_title = ""
    for title in ("微信", "Weixin", "WeChat"):
        hwnd = int(win32gui.FindWindow("Qt51514QWindowIcon", title) or 0)
        if hwnd:
            matched_title = title
            break

    if not hwnd:
        return {
            "diagnosis": "UIAUTOMATION_WECHAT_WINDOW_NOT_FOUND",
            "detail": "Qt51514QWindowIcon WeChat window not found",
        }

    root = safe(lambda: uia.ControlFromHandle(hwnd), None)
    if root is None:
        return {
            "diagnosis": "UIAUTOMATION_ROOT_NOT_AVAILABLE",
            "handle": hwnd,
            "title": matched_title,
        }

    rows = _walk_uia(root)
    meaningful = [
        r for r in rows
        if r.get("depth", 0) > 0
        and (
            r.get("name")
            or r.get("automation_id")
            or str(r.get("class_name") or "").startswith("mmui::")
        )
    ]
    mmui = [r for r in rows if str(r.get("class_name") or "").startswith("mmui::")]
    searchish = [
        r for r in rows
        if any(k in str(r.get("name") or "") for k in ("搜索", "视频号"))
        or any(k in str(r.get("automation_id") or "").lower() for k in ("search", "video", "channel"))
    ]

    visible = len(meaningful) > 3 or bool(mmui)
    return {
        "diagnosis": "CHANNELS_UIAUTOMATION_TREE_VISIBLE" if visible else "CHANNELS_UIAUTOMATION_TREE_NOT_VISIBLE",
        "handle": hwnd,
        "title": matched_title,
        "root": _uia_control_row(root),
        "node_count": len(rows),
        "meaningful_node_count": len(meaningful),
        "mmui_node_count": len(mmui),
        "searchish_nodes": searchish[:30],
        "sample_nodes": rows[:80],
    }


def main() -> None:
    result = {
        "pywinauto": probe_pywinauto(),
        "uiautomation": probe_uiautomation(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
