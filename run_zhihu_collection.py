from __future__ import annotations

"""Zhihu-only collection runner for Tech Design V3 tables 1-5.

This runner intentionally does not import or call the attitude classifier. It runs
keyword discovery (and optional verified key-account creator mode), keeps raw data
local, then exports only tables 1-5 under data_submissions/zhihu/.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import time

from monitor.crawler_runner import find_ingest_jsonl, run_platform
from monitor.creator_runner import run_creator_platform
from monitor.final_realtime_policy import install_final_realtime_policy
from monitor.keyword_pack import apply_keyword_pack
from monitor.zhihu_submission import export_zhihu_submission
from monitor.zhihu_realtime_policy import install_zhihu_scope_aware_realtime_policy
from monitor.zhihu_key_account_search import build_key_account_search_config

ROOT = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    return apply_keyword_pack(cfg, path)


def _load_verified_key_accounts(cfg: dict, config_path: Path) -> list[dict]:
    configured = str(
        cfg.get("zhihu_key_accounts_file")
        or "config/zhihu_key_accounts.local.json"
    ).strip()
    path = Path(configured)
    if not path.is_absolute():
        candidate = config_path.parent / path.name
        path = candidate if candidate.exists() else ROOT / configured
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    accounts = data.get("accounts") if isinstance(data, dict) else []
    return [
        row
        for row in (accounts or [])
        if isinstance(row, dict)
        and bool(row.get("enabled", False))
        and str(row.get("creator_id") or "").strip()
    ]


def _zhihu_platform_cfg(cfg: dict) -> dict:
    for row in cfg.get("platforms") or []:
        if str(row.get("code") or "") == "zhihu":
            return {**row, "enabled": True}
    return {"code": "zhihu", "name": "知乎", "enabled": True}


def prepare_runtime(cfg: dict, node_id: str) -> dict:
    out = dict(cfg)
    out["submission_node_id"] = node_id
    out["interval_seconds"] = 900
    out["realtime_comment_refresh_seconds"] = 900
    out["ingest_comments"] = True
    out["get_comment"] = "yes"
    out["get_sub_comment"] = "yes"
    out["realtime_mode"] = True
    out["key_account_catalog"] = str(
        out.get("key_account_catalog")
        or "config/key_accounts.v3.catalog.json"
    )
    root = Path(out["data_root"])
    if not root.name.endswith("_zhihu"):
        out["data_root"] = str(root.parent / f"{root.name}_zhihu")
    out["platforms"] = [_zhihu_platform_cfg(out)]
    return out


def run_one_cycle(cfg: dict, config_path: Path, node_id: str) -> dict:
    started = datetime.now().astimezone()
    stamp = started.strftime("%Y%m%d_%H%M%S")
    data_root = Path(cfg["data_root"])
    cycle_root = data_root / "raw_runs" / stamp
    cycle_root.mkdir(parents=True, exist_ok=True)

    platform_cfg = _zhihu_platform_cfg(cfg)

    # Pass A: broad topic discovery using the configured Zhihu keyword pack.
    keyword_run = run_platform(cfg, platform_cfg, cycle_root)
    raw_files = find_ingest_jsonl(
        Path(keyword_run.output_dir),
        include_comments=True,
    )

    # Do not open a second browser/login flow when the campaign-keyword pass has
    # already established that official login or verification is required.
    blocked_by_official_auth = keyword_run.state in {
        "VERIFY_REQUIRED",
        "LOGIN_REQUIRED",
    }

    # Pass B: explicitly query every catalogued priority account name. This does
    # not guess creator IDs; it searches public Zhihu results by the documented
    # names, while the installed strict-scope policy still allows comment-detail
    # work only for content that truly matches the formal campaign scope.
    key_account_search_cfg, key_account_search_terms = (
        build_key_account_search_config(cfg, ROOT)
    )
    key_account_search_run = None
    if key_account_search_terms and not blocked_by_official_auth:
        key_account_search_run = run_platform(
            key_account_search_cfg,
            platform_cfg,
            cycle_root,
        )
        raw_files.extend(
            find_ingest_jsonl(
                Path(key_account_search_run.output_dir),
                include_comments=True,
            )
        )
        raw_files = sorted(dict.fromkeys(raw_files))

    key_accounts = _load_verified_key_accounts(cfg, config_path)
    creator_run = None
    if key_accounts and not blocked_by_official_auth:
        creator_run = run_creator_platform(
            cfg,
            platform="zhihu",
            platform_name="知乎",
            creator_ids=[
                str(row["creator_id"]).strip()
                for row in key_accounts
            ],
            run_root=cycle_root,
        )
        raw_files.extend(
            find_ingest_jsonl(
                Path(creator_run.output_dir),
                include_comments=True,
            )
        )
        raw_files = sorted(dict.fromkeys(raw_files))

    # Export even a zero-hit/auth-blocked cycle so downstream delivery always
    # receives the complete five-file package plus an auditable manifest.
    export = export_zhihu_submission(raw_files, cfg, ROOT, node_id)

    result = {
        "platform": "zhihu",
        "node_id": node_id,
        "cycle_started_at": started.isoformat(timespec="seconds"),
        "cycle_finished_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "keyword_run": keyword_run.__dict__,
        "key_account_search_run": (
            key_account_search_run.__dict__
            if key_account_search_run else None
        ),
        "key_account_search_terms": key_account_search_terms,
        "key_account_search_term_count": len(key_account_search_terms),
        "key_account_creator_run": (
            creator_run.__dict__ if creator_run else None
        ),
        "verified_key_accounts_requested": len(key_accounts),
        "input_files": [str(path) for path in raw_files],
        "table_1_to_5_export": export,
        "classification": "not_run_collection_group_scope_only",
        "cadence": {
            "table1_table2_seconds": 900,
            "table3_table4_table5_seconds": 3600,
        },
    }
    status = (
        data_root
        / "status"
        / "latest_zhihu_collection_status.json"
    )
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Zhihu tables 1-5 only; "
            "no attitude classification."
        )
    )
    parser.add_argument(
        "--config",
        default="config/monitoring.local.json",
    )
    parser.add_argument("--node-id", default="zhihu01")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = prepare_runtime(
        load_config(config_path),
        args.node_id,
    )

    install_final_realtime_policy("zhihu")
    install_zhihu_scope_aware_realtime_policy(cfg)

    while True:
        started = time.time()
        result = run_one_cycle(
            cfg,
            config_path,
            args.node_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.once:
            return

        state = str(
            (result.get("keyword_run") or {}).get("state") or ""
        )
        if state in {"VERIFY_REQUIRED", "LOGIN_REQUIRED"}:
            print(
                "[zhihu] official login/verification required; "
                "automatic polling stopped."
            )
            return

        elapsed = time.time() - started
        time.sleep(max(0.0, 900 - elapsed))


if __name__ == "__main__":
    main()
