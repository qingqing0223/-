from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUQI_ROOT = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system")
SUPPORTED_PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "toutiao", "zhihu")
MEDIACRAWLER_PLATFORMS = ("xhs", "dy", "ks", "bili", "wb", "zhihu")
EXPECTED_EVENT_ID = "promotion_week_2026_preheat"
EXPECTED_EVENT_NAME = "2026年民族团结进步宣传周预热阶段舆情监测"
EXPECTED_MONITORING_START_TIME = "2026-09-16T00:00:00+08:00"

REQUIRED_KEYWORDS = (
    "2026年民族团结进步宣传周",
    "首个民族团结进步宣传周",
    "促进民族团结进步，奋进伟大复兴征程",
    "民族团结进步倡议",
    "民族团结进步宣传周主场活动",
    "石榴花开——铸牢中华民族共同体意识",
)
FULL_MATRIX_VALUES = {
    "search_until_exhausted": True,
    "crawler_max_notes_count": 100000,
    "comments_until_exhausted": True,
    "max_comments_count_singlenotes": 100000,
    "get_comment": "yes",
    "get_sub_comment": "yes",
    "ingest_comments": True,
    "max_concurrency_num": 1,
}


def _git(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["git", *args], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _upgrade_local_full_matrix(path: Path) -> tuple[bool, str]:
    if not path.exists() or ".local." not in path.name:
        return False, "not a local config"
    try:
        cfg = _load_json(path)
        changed = False
        for key, value in FULL_MATRIX_VALUES.items():
            if cfg.get(key) != value:
                cfg[key] = value
                changed = True
        scope_values = {
            "event_id": EXPECTED_EVENT_ID,
            "event_name": EXPECTED_EVENT_NAME,
            "monitoring_start_time": EXPECTED_MONITORING_START_TIME,
            "results_date": "",
            "results_date_mode": "auto",
        }
        for key, value in scope_values.items():
            if cfg.get(key) != value:
                cfg[key] = value
                changed = True

        # Keep only active platform entries and ensure Toutiao is present.
        configured_platforms = list(cfg.get("platforms") or [])
        platforms = [
            item for item in configured_platforms
            if str(item.get("code") or "") in SUPPORTED_PLATFORMS
        ]
        if not any(str(item.get("code") or "") == "toutiao" for item in platforms):
            platforms.append({"code": "toutiao", "name": "今日头条", "enabled": True})
        if platforms != configured_platforms:
            changed = True
        cfg["platforms"] = platforms

        existing_keywords = list(cfg.get("keywords") or [])
        if existing_keywords != list(REQUIRED_KEYWORDS):
            cfg["keywords"] = list(REQUIRED_KEYWORDS)
            changed = True
        if changed:
            _write_json(path, cfg)
            return True, "local config upgraded to final full matrix + six campaign keywords"
        return False, "local config already final"
    except Exception as exc:
        return False, f"upgrade failed: {type(exc).__name__}: {exc}"


def _check_json(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        _load_json(path)
        return True, "ok"
    except Exception as exc:
        return False, f"invalid json: {exc}"


def _contains(path: Path, needle: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    try:
        found = needle in path.read_text(encoding="utf-8", errors="replace")
        return found, "installed" if found else "not installed"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _dashboard_health() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3) as resp:
            return resp.status == 200, f"http {resp.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_platform_config(path: Path) -> tuple[bool, str]:
    try:
        cfg = _load_json(path)
        codes = {str(x.get("code") or "") for x in cfg.get("platforms", [])}
        missing = [x for x in SUPPORTED_PLATFORMS if x not in codes]
        if missing:
            return False, "missing platform codes: " + ",".join(missing)
        return True, "7/7 platform codes present"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_keywords(path: Path) -> tuple[bool, str]:
    try:
        cfg = _load_json(path)
        actual = list(cfg.get("keywords") or [])
        missing = [kw for kw in REQUIRED_KEYWORDS if kw not in actual]
        if missing:
            return False, "missing campaign keywords: " + " | ".join(missing)
        return True, "6/6 campaign keywords present"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_monitoring_scope(path: Path) -> tuple[bool, str]:
    try:
        cfg = _load_json(path)
        problems = []
        if str(cfg.get("monitoring_start_time") or "") != EXPECTED_MONITORING_START_TIME:
            problems.append(
                f"monitoring_start_time={cfg.get('monitoring_start_time')!r} "
                f"expected {EXPECTED_MONITORING_START_TIME!r}"
            )
        if bool(cfg.get("realtime_mode", False)):
            if str(cfg.get("results_date_mode") or "").lower() != "auto":
                problems.append("realtime results_date_mode must be 'auto'")
            if str(cfg.get("results_date") or "").strip():
                problems.append("realtime results_date must be empty so daily partitions roll over automatically")
        if problems:
            return False, "; ".join(problems)
        return True, f"scope starts exactly at {EXPECTED_MONITORING_START_TIME}; realtime GitHub partition rolls daily"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_full_matrix(path: Path) -> tuple[bool, str]:
    try:
        cfg = _load_json(path)
        bad = []
        for key, expected in FULL_MATRIX_VALUES.items():
            if cfg.get(key) != expected:
                bad.append(f"{key}={cfg.get(key)!r} expected {expected!r}")
        if bad:
            return False, "; ".join(bad)
        return True, "natural-end paging + first-level comments + nested comments + comment ingestion enabled"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_mediacrawler_platforms(root: Path) -> tuple[bool, str]:
    if not (root / "main.py").exists():
        return False, f"MediaCrawler main.py missing under {root}"
    candidates = [
        root / "config" / "base_config.py",
        root / "cmd_arg" / "arg.py",
        root / "main.py",
    ]
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in candidates if p.exists()
    )
    missing = [code for code in MEDIACRAWLER_PLATFORMS if code not in text]
    if missing:
        return False, "local MediaCrawler code did not expose: " + ",".join(missing)
    return True, "local MediaCrawler exposes the 6 native platform codes; Toutiao uses the project Playwright adapter"


def _check_toutiao_adapter() -> tuple[bool, str]:
    path = ROOT / "scripts" / "toutiao_crawler.py"
    if not path.exists():
        return False, f"missing: {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    required = ("SEARCH_ENDPOINT", "capture_comments", "parent_comment_id", "ip_location", "TOUTIAO_VERIFY_REQUIRED")
    missing = [needle for needle in required if needle not in text]
    if missing:
        return False, "Toutiao adapter missing capabilities: " + ",".join(missing)
    return True, "Toutiao Playwright adapter present: search/detail/comments/nested hierarchy/public region/verification wait"


def _check_mediacrawler_comment_cli(root: Path) -> tuple[bool, str]:
    arg_path = root / "cmd_arg" / "arg.py"
    if not arg_path.exists():
        return False, f"missing: {arg_path}"
    text = arg_path.read_text(encoding="utf-8", errors="replace")
    required = (
        "--get_comment",
        "--get_sub_comment",
        "--max_comments_count_singlenotes",
        "--crawler_max_notes_count",
        "--save_data_path",
    )
    missing = [flag for flag in required if flag not in text]
    if missing:
        return False, "local MediaCrawler is missing CLI flags: " + ",".join(missing)
    return True, "comment/sub-comment/deep-paging/save-path CLI flags present"


def main() -> int:
    parser = argparse.ArgumentParser(description="Deployment preflight for the realtime opinion monitor.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "monitoring.windows.json"),
        help="Runtime monitoring config to validate for local MediaCrawler/data paths.",
    )
    args = parser.parse_args()
    runtime_config = Path(args.config).resolve()

    local_upgraded, local_upgrade_detail = _upgrade_local_full_matrix(runtime_config)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, required: bool = True):
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    add("python", True, sys.version.split()[0])
    add("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    add("uv", shutil.which("uv") is not None, shutil.which("uv") or "not found")
    add(
        "DASHSCOPE_API_KEY",
        bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()),
        (
            "set"
            if os.environ.get("DASHSCOPE_API_KEY", "").strip()
            else "not set; collection is allowed and classifier output may remain unclassified/degraded"
        ),
        required=False,
    )

    json_files = (
        "config/monitoring.windows.json",
        "config/monitoring.student.windows.json",
        "config/monitoring.region.windows.json",
        "config/monitoring.multilingual.windows.json",
        "config/multilingual_keywords.json",
        "config/key_accounts.example.json",
    )
    for rel in json_files:
        ok, detail = _check_json(ROOT / rel)
        add(rel, ok, detail)

    runtime_ok, runtime_detail = _check_json(runtime_config)
    add(f"runtime config:{runtime_config}", runtime_ok, runtime_detail)
    if runtime_ok:
        ok, detail = _check_platform_config(runtime_config)
        add("runtime config seven-platform coverage", ok, detail)
        matrix_ok, matrix_detail = _check_full_matrix(runtime_config)
        upgrade_prefix = f"{local_upgrade_detail}; " if ".local." in runtime_config.name else ""
        add("runtime config full monitoring matrix", matrix_ok, upgrade_prefix + matrix_detail)
        kw_ok, kw_detail = _check_keywords(runtime_config)
        add("runtime config six campaign keywords", kw_ok, kw_detail)
        scope_ok, scope_detail = _check_monitoring_scope(runtime_config)
        add("runtime config monitoring scope", scope_ok, scope_detail)

    for rel in (
        "config/monitoring.windows.json",
        "config/monitoring.student.windows.json",
        "config/monitoring.region.windows.json",
        "config/monitoring.multilingual.windows.json",
    ):
        path = ROOT / rel
        ok, detail = _check_platform_config(path)
        add(f"platform coverage:{rel}", ok, detail)
        matrix_ok, matrix_detail = _check_full_matrix(path)
        add(f"full matrix:{rel}", matrix_ok, matrix_detail)

    try:
        runtime_cfg = _load_json(runtime_config)
        crawler_root = Path(runtime_cfg["media_crawler_root"])
        ok, detail = _check_mediacrawler_platforms(crawler_root)
        add("local MediaCrawler native-platform support", ok, detail)
        ok, detail = _check_mediacrawler_comment_cli(crawler_root)
        add("local MediaCrawler final comment/deep-paging CLI support", ok, detail)
        ok, detail = _check_toutiao_adapter()
        add("Toutiao project adapter", ok, detail)
    except Exception as exc:
        add("local MediaCrawler native-platform support", False, f"{type(exc).__name__}: {exc}")
        add("local MediaCrawler final comment/deep-paging CLI support", False, f"{type(exc).__name__}: {exc}")

    for module in (
        "pipeline.language_detector",
        "pipeline.normalizer",
        "pipeline.classifier",
        "monitor.ingest",
        "monitor.orchestrator",
        "monitor.result_summary",
        "dashboard_adapter.suqi_pusher",
    ):
        try:
            __import__(module)
            add(f"import:{module}", True, "ok")
        except Exception as exc:
            add(f"import:{module}", False, f"{type(exc).__name__}: {exc}")

    dashboard_ok, dashboard_detail = _dashboard_health()
    add("Suqi dashboard health", dashboard_ok, dashboard_detail, required=False)

    region_patch_ok, region_patch_detail = _contains(
        SUQI_ROOT / "db.py", "ON CONFLICT(uid) DO UPDATE SET"
    )
    add("Suqi region/engagement upsert patch", region_patch_ok, region_patch_detail, required=False)
    language_panel_ok, language_panel_detail = _contains(
        SUQI_ROOT / "web" / "index.html", "CORE_MINORITY_LANGS"
    )
    add("Suqi minority-language panel patch", language_panel_ok, language_panel_detail, required=False)
    platform_patch_ok, platform_patch_detail = _contains(
        SUQI_ROOT / "stats.py", 'g = r["platform"] or r["platform_group"] or "其他"'
    )
    add("Suqi separate-platform live statistics patch", platform_patch_ok, platform_patch_detail, required=False)

    rc, remote = _git(["remote", "get-url", "origin"])
    add("git origin", rc == 0 and bool(remote), remote or "missing", required=False)
    rc, user_name = _git(["config", "user.name"])
    add("git user.name", rc == 0 and bool(user_name), user_name or "missing", required=False)
    rc, user_email = _git(["config", "user.email"])
    add("git user.email", rc == 0 and bool(user_email), user_email or "missing", required=False)

    key_accounts_local = ROOT / "config" / "key_accounts.json"
    if key_accounts_local.exists():
        ok, detail = _check_json(key_accounts_local)
        add("config/key_accounts.json", ok, detail, required=False)
    else:
        add("config/key_accounts.json", False, "not configured yet; public publisher account stats are still collected from search results", required=False)

    required_failures = [c for c in checks if c["required"] and not c["ok"]]
    optional_warnings = [c for c in checks if not c["required"] and not c["ok"]]
    result = {
        "ok": not required_failures,
        "runtime_config": str(runtime_config),
        "supported_platforms": list(SUPPORTED_PLATFORMS),
        "local_config_upgraded": local_upgraded,
        "required_failures": len(required_failures),
        "optional_warnings": len(optional_warnings),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
