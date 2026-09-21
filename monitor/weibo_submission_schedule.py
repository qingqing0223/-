from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil

from .weibo_submission_full import (
    TABLE_FILES,
    _excel,
    _read_rows,
    _safe_node,
    export_weibo_submission,
)


TABLE12_KEYS = ("table1", "table2")
TABLE345_KEYS = ("table3", "table4", "table5")
TABLE12_INTERVAL_SECONDS = 15 * 60
TABLE345_INTERVAL_SECONDS = 60 * 60


def _ensure_aware(now: datetime | None = None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.astimezone()
    return value


def _quarter_slot(value: datetime) -> str:
    value = _ensure_aware(value)
    minute = (value.minute // 15) * 15
    return value.replace(
        minute=minute,
        second=0,
        microsecond=0,
    ).isoformat(timespec="seconds")


def _hour_slot(value: datetime) -> str:
    value = _ensure_aware(value)
    return value.replace(
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat(timespec="seconds")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return value if isinstance(value, type(default)) else default


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_event(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False) + "\n")


def _copy_stage_file(stage_dir: Path, formal_dir: Path, table_key: str) -> None:
    source = stage_dir / TABLE_FILES[table_key]
    target = formal_dir / TABLE_FILES[table_key]
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, tmp)
    tmp.replace(target)


def _prepare_stage_root(repo_root: Path, data_root: Path, cfg: dict) -> tuple[Path, dict]:
    stage_root = data_root / "submission_stage_repo" / "weibo"
    stage_config = stage_root / "config"
    stage_config.mkdir(parents=True, exist_ok=True)

    scope_source = repo_root / "config" / "weibo_scope_overrides.json"
    if scope_source.exists():
        shutil.copy2(
            scope_source,
            stage_config / "weibo_scope_overrides.json",
        )

    staged_cfg = dict(cfg)
    catalog_name = str(
        cfg.get("key_account_catalog")
        or "config/key_accounts.v3.catalog.json"
    ).strip()
    catalog_path = Path(catalog_name)
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    if catalog_path.exists():
        staged_cfg["key_account_catalog"] = str(catalog_path.resolve())

    return stage_root, staged_cfg


def publish_staged_weibo_submission(
    stage_dir: Path,
    cfg: dict,
    repo_root: Path,
    data_root: Path,
    node_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Publish WB tables on the formal 15-minute / 1-hour cadence.

    The crawler may continue collecting every 300 seconds. This function only
    controls when stable Table 1-2 and Table 3-5 artifacts are refreshed.
    State is persisted under data_root so process restarts do not resend the
    same time slot.
    """
    now_dt = _ensure_aware(now)
    now_text = now_dt.isoformat(timespec="seconds")
    node = _safe_node(node_id)

    formal_dir = (
        repo_root
        / "data_submissions"
        / "weibo"
        / f"{now_dt.date().isoformat()}_{node}"
    )
    formal_dir.mkdir(parents=True, exist_ok=True)

    state_path = (
        data_root
        / "state"
        / "weibo_submission_schedule.json"
    )
    outbox_path = (
        data_root
        / "outbox"
        / "weibo_submission_publish_events.jsonl"
    )

    state = _read_json(state_path, {})
    targets = state.setdefault("targets", {})
    target_key = f"{now_dt.date().isoformat()}:{node}"
    target = targets.setdefault(target_key, {})

    table12_slot = _quarter_slot(now_dt)
    table345_slot = _hour_slot(now_dt)

    due12 = target.get("last_table12_slot") != table12_slot
    due345 = target.get("last_table345_slot") != table345_slot

    published_groups: list[str] = []

    if due12:
        for key in TABLE12_KEYS:
            _copy_stage_file(stage_dir, formal_dir, key)
        target["last_table12_slot"] = table12_slot
        target["last_table12_published_at"] = now_text
        published_groups.append("table1_table2")

    if due345:
        for key in TABLE345_KEYS:
            _copy_stage_file(stage_dir, formal_dir, key)
        target["last_table345_slot"] = table345_slot
        target["last_table345_published_at"] = now_text
        published_groups.append("table3_table4_table5")

    # Recovery bootstrap: a missing formal table should never make the workbook
    # incomplete even if schedule state survived but files were removed.
    if published_groups:
        for key in TABLE_FILES:
            target_path = formal_dir / TABLE_FILES[key]
            if not target_path.exists():
                _copy_stage_file(stage_dir, formal_dir, key)

        tables = {
            key: _read_rows(formal_dir / filename)
            for key, filename in TABLE_FILES.items()
        }

        manifest = {
            "platform": "wb",
            "node_id": node,
            "generated_at": now_text,
            "monitoring_start_time": str(
                cfg.get("monitoring_start_time") or ""
            ).strip(),
            "classification": "not_run_collection_group_scope_only",
            "internal_collection_interval_seconds": int(
                cfg.get("interval_seconds", 300)
            ),
            "table12_publish_interval_seconds": TABLE12_INTERVAL_SECONDS,
            "table345_publish_interval_seconds": TABLE345_INTERVAL_SECONDS,
            "published_groups": published_groups,
            "last_table12_published_at": target.get(
                "last_table12_published_at", ""
            ),
            "last_table345_published_at": target.get(
                "last_table345_published_at", ""
            ),
            "table12_slot": target.get("last_table12_slot", ""),
            "table345_slot": target.get("last_table345_slot", ""),
            "table1_rows": len(tables["table1"]),
            "table2_rows": len(tables["table2"]),
            "table3_rows": len(tables["table3"]),
            "table4_rows": len(tables["table4"]),
            "table5_rows": len(tables["table5"]),
            "snapshot_hour": table345_slot,
            "unsupported_public_fields_note": (
                "Weibo metrics unavailable from the public collection "
                "interface remain blank; no estimates or substitute zeros."
            ),
        }

        manifest_path = formal_dir / "manifest.json"
        _write_json_atomic(manifest_path, manifest)

        excel_path = formal_dir / "微博监测数据_TechDesignV3.xlsx"
        _excel(excel_path, manifest, tables)

        event = {
            "platform": "wb",
            "node_id": node,
            "published_at": now_text,
            "published_groups": published_groups,
            "output_dir": str(formal_dir),
            "manifest": str(manifest_path),
            "excel": str(excel_path),
            "table_files": {
                key: str(formal_dir / filename)
                for key, filename in TABLE_FILES.items()
            },
            "delivery_state": "formal_artifacts_ready",
        }
        _append_event(outbox_path, event)

    targets[target_key] = target
    state["targets"] = targets
    state["updated_at"] = now_text
    _write_json_atomic(state_path, state)

    return {
        "output_dir": str(formal_dir),
        "manifest": str(formal_dir / "manifest.json"),
        "excel": str(formal_dir / "微博监测数据_TechDesignV3.xlsx"),
        "table_files": {
            key: str(formal_dir / filename)
            for key, filename in TABLE_FILES.items()
        },
        "published_groups": published_groups,
        "table12_published": "table1_table2" in published_groups,
        "table345_published": "table3_table4_table5" in published_groups,
        "table12_slot": table12_slot,
        "table345_slot": table345_slot,
        "publish_state": str(state_path),
        "publish_outbox": str(outbox_path),
    }


def run_scheduled_weibo_submission(
    files: list[Path],
    cfg: dict,
    repo_root: Path,
    node_id: str = "wb01",
    raw_root: Path | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Update internal WB staging every crawl cycle, publish on formal cadence."""
    now_dt = _ensure_aware(now)
    data_root = Path(cfg["data_root"])
    node = _safe_node(node_id)

    stage_root, staged_cfg = _prepare_stage_root(
        repo_root,
        data_root,
        cfg,
    )

    formal_dir = (
        repo_root
        / "data_submissions"
        / "weibo"
        / f"{now_dt.date().isoformat()}_{node}"
    )
    seed_dir = formal_dir if formal_dir.exists() else None

    stage_result = export_weibo_submission(
        files,
        staged_cfg,
        stage_root,
        node,
        raw_root=raw_root,
        seed_dir=seed_dir,
        now=now_dt,
    )

    publish_result = publish_staged_weibo_submission(
        Path(stage_result["output_dir"]),
        cfg,
        repo_root,
        data_root,
        node,
        now=now_dt,
    )

    return {
        **stage_result,
        **publish_result,
        "accepted_rows": int(stage_result.get("accepted_rows") or 0),
        "stage_output_dir": stage_result["output_dir"],
        "stage_manifest": stage_result["manifest"],
        "stage_excel": stage_result["excel"],
        "internal_collection_interval_seconds": int(
            cfg.get("interval_seconds", 300)
        ),
        "table12_publish_interval_seconds": TABLE12_INTERVAL_SECONDS,
        "table345_publish_interval_seconds": TABLE345_INTERVAL_SECONDS,
    }
