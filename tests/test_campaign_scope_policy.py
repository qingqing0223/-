from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from monitor.campaign_scope import (
    POLICY_VERSION,
    CORE_KEYWORDS,
    ALIASES,
    TYPO_RECOVERY_TERMS,
    COMBINATION_QUERIES,
    RELATED_RECOVERY_QUERIES,
    all_search_queries,
    evaluate_campaign_relevance,
    matched_campaign_terms,
    select_realtime_queries,
)
from monitor.keyword_pack import apply_keyword_pack


class CampaignScopePolicyTests(unittest.TestCase):
    def test_core_keyword_set_matches_20260923_requirement(self):
        self.assertEqual(CORE_KEYWORDS, (
            "民族团结进步宣传周",
            "2026年民族团结进步宣传周",
            "首个民族团结进步宣传周",
            "民族团结进步宣传周启动",
            "民族团结进步宣传周活动",
            "民族团结进步宣传周主场活动",
            "2026年民族团结进步宣传周主场活动",
            "民族团结进步宣传周主题宣传片",
            "民族团结进步倡议",
            "民族团结进步倡议书",
            "促进民族团结进步，奋进伟大复兴征程",
        ))

    def test_runtime_expansion_contains_alias_typo_combination_and_related_recovery(self):
        queries = all_search_queries()
        for term in (
            "民族团结宣传周",
            "民族团结进取宣传周",
            "民族团结进步 主题宣传片",
            "石榴花开 宣传周",
            "铸牢中华民族共同体意识 9月21日 27日",
        ):
            self.assertIn(term, queries)
        self.assertEqual(len(queries), len(set(queries)))
        self.assertGreater(
            len(queries),
            len(CORE_KEYWORDS) + len(ALIASES) + len(TYPO_RECOVERY_TERMS),
        )

    def test_apply_keyword_pack_expands_without_multilingual_file(self):
        cfg = {
            "event_id": "promotion_week_2026_preheat",
            "keywords": list(CORE_KEYWORDS),
            "campaign_search_expand": True,
            "campaign_keyword_policy_version": POLICY_VERSION,
        }
        with tempfile.TemporaryDirectory() as td:
            out = apply_keyword_pack(cfg, Path(td) / "monitoring.local.json")
        self.assertEqual(out["keywords"], all_search_queries())
        self.assertTrue(out["keyword_pack_status"]["campaign_search"]["enabled"])
        self.assertEqual(
            out["keyword_pack_status"]["campaign_search"]["policy_version"],
            POLICY_VERSION,
        )

    def test_realtime_keeps_all_core_and_rotates_only_supplemental_queries(self):
        all_queries = all_search_queries()
        first = select_realtime_queries(all_queries, supplemental_count=5, bucket=0)
        second = select_realtime_queries(all_queries, supplemental_count=5, bucket=1)
        for keyword in CORE_KEYWORDS:
            self.assertIn(keyword, first)
            self.assertIn(keyword, second)
        self.assertEqual(len(first), len(CORE_KEYWORDS) + 5)
        self.assertEqual(len(second), len(CORE_KEYWORDS) + 5)
        self.assertNotEqual(first, second)

    def test_matched_keywords_include_combination_queries(self):
        row = {
            "title": "2026年民族团结进步主题宣传片正式发布",
            "desc": "宣传周主场活动同步启动",
        }
        matched = matched_campaign_terms(row)
        self.assertIn("民族团结进步 主题宣传片", matched)
        self.assertIn("民族团结进步 主场活动", matched)

    def test_search_broad_admission_strict(self):
        direct = evaluate_campaign_relevance({
            "title": "民族团结进步宣传周活动正式启动",
        })
        self.assertTrue(direct.valid)

        typo_without_anchor = evaluate_campaign_relevance({
            "title": "民族团结进取宣传周",
        })
        self.assertFalse(typo_without_anchor.valid)

        typo_with_anchor = evaluate_campaign_relevance({
            "title": "2026民族团结进取宣传周活动",
        })
        self.assertTrue(typo_with_anchor.valid)

        related_only = evaluate_campaign_relevance({
            "title": "石榴花开",
            "desc": "铸牢中华民族共同体意识",
        })
        self.assertFalse(related_only.valid)

        related_with_week = evaluate_campaign_relevance({
            "title": "石榴花开",
            "desc": "民族团结进步宣传周主题活动",
        })
        self.assertTrue(related_with_week.valid)

        old = evaluate_campaign_relevance({
            "title": "2025年民族团结进步宣传周回顾",
        })
        self.assertFalse(old.valid)

        month = evaluate_campaign_relevance({
            "title": "民族团结进步宣传月启动",
        })
        self.assertFalse(month.valid)

        unrelated = evaluate_campaign_relevance({
            "title": "某品牌主题宣传片正式发布",
            "source_keyword": "民族团结进步 主题宣传片",
        })
        self.assertFalse(unrelated.valid)


if __name__ == "__main__":
    unittest.main()
