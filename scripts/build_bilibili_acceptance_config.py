from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from monitor.campaign_scope import POLICY_VERSION, CORE_KEYWORDS


FORMAL_KEYWORDS = list(CORE_KEYWORDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--media-crawler-root", default="")
    args = ap.parse_args()

    base = Path(args.base).resolve()
    output = Path(args.output).resolve()
    cfg = json.loads(base.read_text(encoding="utf-8-sig"))

    if args.media_crawler_root:
        cfg["media_crawler_root"] = str(
            Path(args.media_crawler_root).resolve()
        )

    data_root = Path(str(cfg["data_root"]))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg["data_root"] = str(
        data_root.parent / f"{data_root.name}_bili_acceptance_{stamp}"
    )
    cfg["event_id"] = "promotion_week_2026_preheat"
    cfg["event_name"] = "2026年民族团结进步宣传周预热阶段舆情监测"
    cfg["monitoring_start_time"] = "2026-09-16T00:00:00+08:00"
    cfg["keywords"] = list(FORMAL_KEYWORDS)
    cfg["campaign_search_expand"] = True
    cfg["campaign_strict_admission"] = True
    cfg["campaign_keyword_policy_version"] = POLICY_VERSION
    cfg["realtime_supplemental_keywords_per_cycle"] = 5
    cfg["realtime_mode"] = True
    cfg["interval_seconds"] = 300
    cfg["get_comment"] = "yes"
    cfg["get_sub_comment"] = "yes"
    cfg["ingest_comments"] = True
    cfg["classifier_concurrency"] = max(int(cfg.get("classifier_concurrency", 4)), 12)

    cfg["bili_realtime_discovery_max_notes_count"] = 20
    cfg["bili_realtime_search_concurrency"] = 4
    cfg["bili_realtime_items_per_keyword"] = 5
    cfg["bili_realtime_search_timeout_seconds"] = 120
    cfg["bili_realtime_detail_max_items_per_cycle"] = 2
    cfg["bili_realtime_detail_budget_seconds"] = 70
    cfg["bili_realtime_candidate_timeout_seconds"] = 70
    cfg["bili_realtime_max_comments_per_video"] = 20
    cfg["bili_realtime_subcomment_root_cap"] = 2
    cfg["bili_realtime_subcomment_page_cap"] = 1

    # Disable unrelated platform execution in this acceptance config.
    for platform in cfg.get("platforms", []):
        platform["enabled"] = platform.get("code") == "bili"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "config": str(output),
        "data_root": cfg["data_root"],
        "monitoring_start_time": cfg["monitoring_start_time"],
        "keywords": cfg["keywords"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
