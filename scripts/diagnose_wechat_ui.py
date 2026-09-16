from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

try:
    import psutil
    from pywinauto import Desktop
except Exception as exc:
    raise SystemExit(f"Missing dependency: {type(exc).__name__}: {exc}")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def summarize_window(spec, backend: str) -> dict:
    try:
        wrapper = spec.wrapper_object()
    except Exception:
        wrapper = spec

    result = {
        "backend": backend,
        "handle": safe(lambda: int(wrapper.handle), 0),
        "title": safe(lambda: wrapper.window_text(), "") or "",
        "class_name": safe(lambda: wrapper.class_name(), "") or "",
        "visible": bool(safe(lambda: wrapper.is_visible(), False)),
        "enabled": bool(safe(lambda: wrapper.is_enabled(), False)),
    }

    if backend == "uia":
        descendants = safe(lambda: wrapper.descendants(), []) or []
        result["uia_descendant_count"] = len(descendants)
        texts = []
        for item in descendants[:250]:
            text = safe(lambda i=item: i.window_text(), "") or ""
            text = str(text).strip()
            if text and text not in texts:
                texts.append(text[:160])
            if len(texts) >= 30:
                break
        result["uia_sample_texts"] = texts
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose whether Windows UI Automation can see the official WeChat desktop UI tree.")
    parser.add_argument("--save", default="", help="Optional JSON output path")
    args = parser.parse_args()

    processes = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = str(proc.info.get("name") or "")
            if name.lower() in {"weixin.exe", "wechat.exe"}:
                processes.append({
                    "pid": int(proc.info["pid"]),
                    "name": name,
                    "exe": str(proc.info.get("exe") or ""),
                })
        except Exception:
            continue

    report = {
        "admin": is_admin(),
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "processes": processes,
        "windows": [],
        "diagnosis": [],
    }

    for proc in processes:
        pid = proc["pid"]
        for backend in ("uia", "win32"):
            try:
                desktop = Desktop(backend=backend)
                windows = desktop.windows(process=pid, visible_only=False)
            except Exception as exc:
                report["windows"].append({
                    "backend": backend,
                    "pid": pid,
                    "enumeration_error": f"{type(exc).__name__}: {exc}",
                })
                continue
            for spec in windows:
                row = summarize_window(spec, backend)
                row["pid"] = pid
                report["windows"].append(row)

    uia_rows = [r for r in report["windows"] if r.get("backend") == "uia" and r.get("handle")]
    visible_uia = [r for r in uia_rows if r.get("visible")]
    rich_uia = [r for r in visible_uia if int(r.get("uia_descendant_count") or 0) > 5]

    if not processes:
        report["diagnosis"].append("WECHAT_NOT_RUNNING")
    elif not uia_rows:
        report["diagnosis"].append("UIA_NO_WECHAT_WINDOW")
    elif not rich_uia:
        report["diagnosis"].append("UIA_TREE_NOT_VISIBLE")
    else:
        report["diagnosis"].append("UIA_TREE_VISIBLE")

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.save:
        path = Path(args.save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
