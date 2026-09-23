from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from wechat.mp_frontend import export_frontend
from wechat.mp_poms import POMS_FIELDS, validate_schema


def article(**changes):
    return {
        "content_id": "wxmp_test1", "author": "真实账号", "author_id": None,
        "title": "2026年民族团结进步宣传周", "content": "公开搜索摘要",
        "publish_time": "2026-09-21T12:00:00+08:00", "collected_at": "2026-09-21T12:10:00+08:00",
        "url": "https://weixin.sogou.com/link?url=public-result", "canonical_url": "",
        "matched_keywords": ["民族团结进步宣传周"], "candidate_eligible": True,
        "review_status": "是", "is_valid": True, "invalid_reason": "",
        "views": None, "likes": None, "comments": None, "reposts": None, "shares": None, "favorites": None,
        "discovery_sources": ["sogou"], "detail_status": "URL_UNRESOLVED",
        "first_discovered_at": "2026-09-21T12:10:00+08:00", "history_batch": "2026-09-21_wechatmp02",
        **changes,
    }


def run(tmp_path, rows):
    state = SimpleNamespace(records=rows, source_status={"bing": {"status": "ERROR", "reason": "timeout"}})
    cfg = {"wechat_mp_frontend_root": str(tmp_path), "wechat_mp_exported_at": "2026-09-23T21:00:00+08:00",
           "current_period_start": "2026-09-23T00:00:00+08:00"}
    result = export_frontend(cfg, state)
    snapshot = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    return result, snapshot


def test_unknown_remains_unknown_and_poms_placeholders_are_explicit(tmp_path):
    rows = [article(), article(content_id="pending", author="另一个账号", review_status="待核验", is_valid=False,
                               invalid_reason="需要人工核验")]
    before = deepcopy(rows)
    result, snapshot = run(tmp_path, rows)
    assert rows == before
    assert result["table_counts"] == [2, 0, 1, 0, 1]
    assert snapshot["tables"]["table3"][0]["阅读/播放量"] is None
    assert snapshot["records"][0]["views"] is None
    arrays = [snapshot["poms_tables"][f"table{i}"] for i in range(1, 6)]
    assert arrays[2][0]["view_or_play_count"] == 0
    assert arrays[0][0]["publisher_account_id"] == arrays[4][0]["account_id"]
    assert arrays[0][1]["is_valid_monitoring_data"] is False
    assert arrays[0][1]["invalid_reason"] == "需要人工核验"
    assert arrays[0][0]["original_content_url"].startswith("https://weixin.sogou.com/link")
    assert arrays[1] == arrays[3] == []
    assert result["metadata"]["reliable_interactions"]["views"]["known_sum"] is None
    assert any(r["field"] == "view_or_play_count" and r["is_observation"] is False
               for r in result["metadata"]["poms_placeholders"])
    validate_schema(arrays)
    assert result["schema_conflicts"] == []


def test_history_and_new_discovery_and_publication_and_enrichment_are_separate(tmp_path):
    rows = [article(), article(content_id="today", history_batch=None,
                               publish_time="2026-09-23T12:00:00+08:00",
                               first_discovered_at="2026-09-23T12:10:00+08:00"),
            article(content_id="discovered_old", history_batch=None,
                    first_discovered_at="2026-09-23T12:20:00+08:00",
                    detail_completed_at="2026-09-23T12:30:00+08:00", discovery_sources=["bing", "sogou"])]
    _, snapshot = run(tmp_path, rows)
    m = snapshot["metadata"]
    assert m["cumulative"]["valid_articles"] == 3
    assert m["history"]["total_candidates"] == 1
    assert m["published_today"]["total_candidates"] == m["current_period"]["total_candidates"] == 1
    assert m["new_discoveries_today"]["total_candidates"] == 2
    assert m["details_completed_today"] == 1
    assert m["source_counts"]["bing"]["total_candidates"] == 1
    assert m["source_status"]["bing"]["status"] == "ERROR"


def test_missing_publish_time_is_quarantined_not_invented(tmp_path):
    rows = [article(), article(content_id="unknown_time", publish_time=None)]
    _, snapshot = run(tmp_path, rows)
    assert len(snapshot["tables"]["table1"]) == 1
    assert snapshot["quarantine"][0]["record"]["publish_time"] is None
    assert snapshot["schema_conflicts"][0]["field"] == "published_at"
    assert len(snapshot["poms_tables"]["table1"]) == 1


def test_schema_failure_does_not_block_other_basic_records(tmp_path):
    rows = [article(), article(content_id="bad", author="另一个账号", collected_at="invalid", likes=-1)]
    _, snapshot = run(tmp_path, rows)
    assert len(snapshot["tables"]["table1"]) == 2
    assert len(snapshot["poms_tables"]["table1"]) == 1
    assert snapshot["poms_tables"]["table1"][0]["published_content_id"] == "wxmp_test1"
    assert any(r["field"] == "collected_at" for r in snapshot["schema_conflicts"])
    assert snapshot["records"][1]["likes"] == -1
    assert all(r["corresponding_published_content_id"] == "wxmp_test1" for r in snapshot["poms_tables"]["table3"])


def test_true_zero_is_known_and_placeholder_zero_is_not(tmp_path):
    _, snapshot = run(tmp_path, [article(views=0), article(content_id="missing")])
    counts = snapshot["metadata"]["reliable_interactions"]["views"]
    assert counts == {"known_sum": 0, "known_records": 1, "unknown_records": 1, "complete_sum": None}


def test_sample_order_and_all_files_match_atomic_snapshot(tmp_path):
    _, snapshot = run(tmp_path, [article()])
    sample_dir = Path(__file__).resolve().parents[1] / "batch_test_samples"
    for index in range(1, 6):
        sample = next(sample_dir.glob(f"{index:02d}_batch_*.json"))
        assert list(json.loads(sample.read_text(encoding="utf-8"))[0]) == POMS_FIELDS[index-1]
        assert json.loads((tmp_path / f"table{index}.json").read_text(encoding="utf-8")) == snapshot["tables"][f"table{index}"]
        assert json.loads((tmp_path / f"table{index}_batch.json").read_text(encoding="utf-8")) == snapshot["poms_tables"][f"table{index}"]
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_link_does_not_become_fake_poms_url(tmp_path):
    _, snapshot = run(tmp_path, [article(url=None)])
    assert snapshot["poms_tables"]["table1"] == []
    assert "missing_public_article_or_result_url" in snapshot["quarantine"][0]["reasons"]
