from __future__ import annotations

import json
from pathlib import Path

from monitor.zhihu_key_account_search import (
    build_key_account_search_config,
    load_key_account_search_terms,
)


def _write_catalog(root: Path) -> None:
    path = root / "config" / "key_accounts.v3.catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "account_type": "中央媒体",
                        "accounts": ["人民日报", "新华社"],
                    },
                    {
                        "account_type": "地方媒体",
                        "accounts": ["新疆日报/石榴云"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_key_account_terms_expand_composite_aliases_without_guessing_ids(tmp_path: Path):
    _write_catalog(tmp_path)
    cfg = {
        "key_account_catalog": "config/key_accounts.v3.catalog.json",
    }
    terms = load_key_account_search_terms(tmp_path, cfg)
    assert terms == ["人民日报", "新华社", "新疆日报", "石榴云"]


def test_key_account_search_config_keeps_small_discovery_cap(tmp_path: Path):
    _write_catalog(tmp_path)
    cfg = {
        "key_account_catalog": "config/key_accounts.v3.catalog.json",
        "keywords": ["2026年民族团结进步宣传周"],
        "zhihu_key_account_discovery_max_notes_count": 5,
        "get_comment": "no",
    }
    out, terms = build_key_account_search_config(cfg, tmp_path)

    assert terms == ["人民日报", "新华社", "新疆日报", "石榴云"]
    assert out["keywords"] == terms
    assert out["zhihu_realtime_discovery_max_notes_count"] == 5
    assert out["realtime_mode"] is True
    assert out["get_comment"] == "yes"
    assert out["get_sub_comment"] == "yes"


def test_real_catalog_exposes_all_documented_priority_names():
    root = Path(__file__).resolve().parents[1]
    terms = load_key_account_search_terms(
        root,
        {"key_account_catalog": "config/key_accounts.v3.catalog.json"},
    )
    # 50 catalog rows, with three slash-labelled rows expanding to two aliases.
    assert len(terms) == 53
    for expected in (
        "人民日报",
        "国家民委",
        "内蒙古卫视",
        "北京日报",
        "新疆日报",
        "石榴云",
        "云南日报",
        "云新闻",
        "广西日报",
        "广西云",
    ):
        assert expected in terms
