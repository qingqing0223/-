from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.result_summary import build_summary

EXPECTED_KEYWORDS = [
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _platform_root(cfg: dict) -> Path:
    base = Path(cfg["data_root"])
    return base.parent / f"{base.name}_wechat_mp"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config" / "monitoring.wechat.local.json"))
    ap.add_argument("--config-only", action="store_true")
    args = ap.parse_args()

    path = Path(args.config).resolve()
    checks = []

    def add(name: str, ok: bool, detail, required: bool = True):
        checks.append({"name": name, "ok": bool(ok), "required": bool(required), "detail": detail})

    if not path.exists():
        add("config", False, f"missing: {path}")
        cfg = {}
    else:
        try:
            cfg = _load(path)
            add("config", True, str(path))
        except Exception as exc:
            cfg = {}
            add("config", False, f"invalid json: {type(exc).__name__}: {exc}")

    if cfg:
        keywords = [str(x).strip() for x in cfg.get("keywords", []) if str(x).strip()]
        add("six official keywords", keywords == EXPECTED_KEYWORDS, {"configured": keywords})
        add("monitoring start", str(cfg.get("monitoring_start_time") or "") == "2026-09-16T00:00:00+08:00", cfg.get("monitoring_start_time"))
        add("five-minute polling", int(cfg.get("wechat_mp_interval_seconds", 0) or 0) == 300, cfg.get("wechat_mp_interval_seconds"))
        add("deep paging", bool(cfg.get("wechat_mp_search_until_exhausted", False)), cfg.get("wechat_mp_search_until_exhausted"))
        add("page safety cap", int(cfg.get("wechat_mp_max_pages", 0) or 0) >= 1000, cfg.get("wechat_mp_max_pages"))
        add("result safety cap", int(cfg.get("wechat_mp_max_results_per_keyword", 0) or 0) >= 100000, cfg.get("wechat_mp_max_results_per_keyword"))
        dash = cfg.get("dashboard") or {}
        add("dashboard configured", bool(dash.get("enabled")) and bool(dash.get("ingest_url")), dash, required=False)
        add("DashScope API key", bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()), "set" if os.environ.get("DASHSCOPE_API_KEY") else "missing")
        add("Chrome", shutil.which("chrome") is not None or any(Path(p).exists() for p in [
            Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]), "required for visible Sogou-Weixin browser")
        try:
            import opinion_monitor_v2  # noqa: F401
            add("opinion_monitor_v2", True, "import ok")
        except Exception as exc:
            add("opinion_monitor_v2", False, f"{type(exc).__name__}: {exc}")

        # These are source capability statements, not failures.
        add("public article search", True, "supported via public Sogou-Weixin search", required=False)
        add("article comments / nested replies", False, "not exposed by the current public Sogou-Weixin search source; do not interpret as zero comments", required=False)
        add("public IP-region labels", False, "not exposed by the current public Sogou-Weixin search result source", required=False)
        add("reliable complete engagement", False, "not consistently exposed by the current public search source", required=False)

        if not args.config_only:
            root = _platform_root(cfg)
            summary = build_summary([root] if root.exists() else [], str(cfg.get("monitoring_start_time") or ""))
            totals = summary.get("totals") or {}
            runtime = summary.get("runtime") or []
            payload = {
                "schema_version": summary.get("schema_version"),
                "data_root": str(root),
                "latest_seen_time": summary.get("latest_seen_time"),
                "unique_records": totals.get("unique_records", 0),
                "public_publisher_accounts": totals.get("public_publisher_accounts", 0),
                "keywords": summary.get("keywords") or {},
                "attitude": summary.get("attitude") or {},
                "v2_status": summary.get("v2_status") or {},
                "v2_type": summary.get("v2_type") or {},
                "source_types": summary.get("source_types") or {},
                "languages": summary.get("languages") or {},
                "minority_languages": summary.get("minority_languages") or {},
                "public_account_stats": summary.get("public_account_stats") or [],
                "runtime": runtime,
                "limitations": {
                    "comments_and_nested_replies": "unavailable_from_current_public_source",
                    "public_ip_region": "unavailable_from_current_public_source",
                    "complete_engagement_metrics": "not_reliably_available_from_current_public_source",
                },
            }
        else:
            payload = {"mode": "config-only"}
    else:
        payload = {}

    required_failures = [x for x in checks if x["required"] and not x["ok"]]
    result = {
        "ok": not required_failures,
        "platform": "wechat_mp",
        "required_failures": len(required_failures),
        "checks": checks,
        "result": payload,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
