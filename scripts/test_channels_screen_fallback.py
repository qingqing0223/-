from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wechat.channels_screen import collect_one


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the screen-coordinate fallback for WeChat Channels with one keyword.")
    parser.add_argument("--config", default=str(ROOT / "config" / "monitoring.wechat.local.json"))
    parser.add_argument("--keyword", default="")
    args = parser.parse_args()

    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        print(json.dumps({"status": "CONFIG_MISSING", "config": str(cfg_path)}, ensure_ascii=False, indent=2))
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    keywords = [str(x).strip() for x in cfg.get("keywords", []) if str(x).strip()]
    keyword = args.keyword.strip() or (keywords[0] if keywords else "2026年民族团结进步宣传周")

    try:
        result = collect_one(cfg, keyword)
    except Exception as exc:
        result = {
            "status": "SCREEN_FALLBACK_ERROR",
            "keyword": keyword,
            "error": f"{type(exc).__name__}:{exc}",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    safe_records = []
    for row in result.get("records") or []:
        safe_records.append({
            "title": row.get("title", ""),
            "author": row.get("author", ""),
            "publish_time": row.get("publish_time", ""),
            "content": row.get("content", "")[:300],
        })
    output = {k: v for k, v in result.items() if k != "records"}
    output["records"] = safe_records
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
