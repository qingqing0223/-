from __future__ import annotations

import json

try:
    from pywinauto import Desktop
except Exception as exc:
    raise SystemExit(f"Missing dependency: {type(exc).__name__}: {exc}")


def safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def main() -> None:
    desktop = Desktop(backend="uia")
    rows = []

    for wrapper in desktop.windows(visible_only=True):
        class_name = safe(lambda w=wrapper: w.class_name(), "") or ""
        title = safe(lambda w=wrapper: w.window_text(), "") or ""
        if class_name != "Chrome_WidgetWin_0" and title not in {"微信", "WeChat"}:
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

        score = 0
        joined = " ".join(texts)
        if class_name == "Chrome_WidgetWin_0":
            score += 2
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
            "sample_texts": texts,
            "candidate_score": score,
        })

    rows.sort(key=lambda x: x["candidate_score"], reverse=True)
    diagnosis = "CHANNELS_UIA_WINDOW_VISIBLE" if rows and rows[0]["candidate_score"] >= 8 else "CHANNELS_UIA_WINDOW_NOT_FOUND"
    print(json.dumps({"diagnosis": diagnosis, "candidates": rows[:10]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
