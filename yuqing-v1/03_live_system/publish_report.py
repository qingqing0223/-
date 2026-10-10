#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把生成好的报告发布到公开页面目录（web/assets/reports/），供大屏页直接下载。

用法（在 03_live_system 目录下执行）:
    python3 publish_report.py /path/to/报告.docx
    python3 publish_report.py 报告.docx --id 20261010-第2期 --title "民族团结进步宣传周舆情专报（第2期）" --date 2026-10-10

做的事:
    1. 复制报告文件到 web/assets/reports/
    2. 新增/更新 web/assets/reports/manifest.json（按发布时间倒序）
    3. 打印后续 git 命令（需手动执行）

说明:
    - 页面下载的是静态文件，全程不需要 API Key（密钥不应出现在页面里）。
    - 发布即公开：请先确认该期报告允许对外公开，再 git push。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPORTS_DIR = BASE / "web" / "assets" / "reports"
MANIFEST = REPORTS_DIR / "manifest.json"
CN_TZ = timezone(timedelta(hours=8))


def load_manifest() -> dict:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("reports", [])
            return data
    except Exception:
        pass
    return {"updated_at": "", "latest": None, "reports": []}


def guess_date(name: str) -> str:
    match = re.search(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", name)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="发布报告到 web/assets/reports/（公开页面直接下载）")
    parser.add_argument("report", help="报告文件路径（docx / pdf）")
    parser.add_argument("--id", dest="report_id", default="", help="报告编号（默认取文件名）")
    parser.add_argument("--title", default="", help="展示标题（默认取文件名）")
    parser.add_argument("--date", default="", help="报告日期 YYYY-MM-DD（默认从文件名推断，否则今天）")
    args = parser.parse_args()

    source = Path(args.report).expanduser().resolve()
    if not source.is_file():
        print(f"[x] 找不到文件: {source}")
        return 1

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    destination = REPORTS_DIR / source.name
    if source != destination:
        shutil.copy2(source, destination)

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    entry = {
        "id": args.report_id or source.stem,
        "title": args.title or source.stem,
        "date": args.date or guess_date(source.stem),
        "file": source.name,
        "size": destination.stat().st_size,
        "sha256": digest,
        "published_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
    }

    manifest = load_manifest()
    reports = [r for r in manifest["reports"] if isinstance(r, dict) and r.get("id") != entry["id"]]
    reports.append(entry)
    reports.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    manifest = {
        "updated_at": entry["published_at"],
        "latest": reports[0]["id"],
        "reports": reports,
    }
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)

    print(f"[ok] 已发布到页面目录: {destination}")
    print(f"     id={entry['id']}  date={entry['date']}  size={entry['size']}B  sha256={digest[:12]}...")
    print()
    print("下一步（需手动执行；发布即公开，请确认该期报告允许对外）:")
    print("    git add web/assets/reports")
    print(f"    git commit -m \"publish report {entry['id']}\"")
    print("    git push")
    return 0


if __name__ == "__main__":
    main()
