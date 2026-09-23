"""Offline display v2 re-export from an existing submission, preserving evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wechat.common import now_cn
from wechat.mp_export import export_submission, atomic_json, FILES, WORKBOOK


def reexport(batch: Path, config: dict) -> dict:
    batch = batch.resolve()
    raw = batch / "search_contents.jsonl"
    original_book = batch / WORKBOOK
    protected = [raw, original_book]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    summary = json.loads((batch / "summary.json").read_text(encoding="utf-8-sig"))
    cfg = dict(config)
    date, node = batch.name.split("_", 1)
    cfg.update(wechat_mp_submission_root=str(batch.parent), wechat_mp_submission_date=date, wechat_mp_node_id=node)
    if cfg["monitoring_start_time"] != summary["monitoring_start_time"] or cfg.get("monitoring_end_time") != summary.get("monitoring_end_time"):
        raise ValueError("Config time range differs from the existing submission")
    catalog_path = Path(cfg.get("wechat_mp_key_accounts", "config/key_accounts.wechat_mp.json"))
    if not catalog_path.is_absolute():
        catalog_path = ROOT / catalog_path
    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    backup = batch / "before_display_v2"
    backup.mkdir(exist_ok=True)
    for name in [*FILES, *[f"table{i}_batch.json" for i in range(1, 6)], "summary.json", "README.txt", "export_snapshot.json", "poms_conversion.json"]:
        source = batch / name
        if source.exists() and not (backup / name).exists():
            shutil.copy2(source, backup / name)
    result = export_submission(rows, cfg, catalog, now_cn().isoformat(timespec="seconds"),
                               summary["collector"], force=True, preserve_raw=True)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    if before != after:
        raise AssertionError("Original evidence changed during display export")
    receipt = {"original_files_unchanged": True, "sha256_before": before, "sha256_after": after,
               "network_requests": 0, "export": result}
    atomic_json(batch / "display_v2_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, default=ROOT / "data_submissions/wechat_mp/2026-09-21_wechatmp02")
    parser.add_argument("--config", type=Path, default=ROOT / "config/monitoring.wechat.2026-09-21.json")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    print(json.dumps(reexport(args.batch_dir, cfg), ensure_ascii=False, indent=2))
