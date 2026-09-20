from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "toutiao_crawler.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("toutiao_crawler_test_module", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Toutiao adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToutiaoFinalStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_adapter()

    def test_canonical_article_and_video_urls(self):
        self.assertEqual(
            self.mod.canonical_url("https://www.toutiao.com/article/123456/?x=1"),
            "https://www.toutiao.com/article/123456/",
        )
        self.assertEqual(
            self.mod.canonical_url("https://www.toutiao.com/video/998877/"),
            "https://www.toutiao.com/video/998877/",
        )

    def test_comment_payload_keeps_root_and_nested_parent_links(self):
        payload = {
            "data": {
                "comments": [
                    {
                        "id": "root-1",
                        "text": "一级评论",
                        "reply_count": 1,
                        "ip_location": "IP属地：山东",
                        "user": {"user_id": "u1", "name": "甲"},
                        "reply_data": {
                            "reply_list": [
                                {
                                    "id": "child-1",
                                    "text": "楼中楼回复",
                                    "ip_region": "北京",
                                    "user": {"user_id": "u2", "name": "乙"},
                                }
                            ]
                        },
                    }
                ]
            }
        }
        rows = {row["comment_id"]: row for row in self.mod.parse_comment_payload(payload, "article-9")}
        self.assertEqual(rows["root-1"]["parent_comment_id"], "")
        self.assertEqual(rows["root-1"]["root_comment_id"], "root-1")
        self.assertEqual(rows["root-1"]["ip_location"], "山东")
        self.assertEqual(rows["child-1"]["parent_comment_id"], "root-1")
        self.assertEqual(rows["child-1"]["root_comment_id"], "root-1")
        self.assertEqual(rows["child-1"]["comment_level"], 2)
        self.assertEqual(rows["child-1"]["ip_location"], "北京")

    def test_region_rejects_non_province_noise(self):
        self.assertEqual(self.mod.coarse_region("IP属地：广东"), "广东")
        self.assertEqual(self.mod.coarse_region("来自：内蒙古"), "内蒙古")
        self.assertEqual(self.mod.coarse_region("127.0.0.1"), "")

    def test_unknown_engagement_count_is_not_fabricated_zero(self):
        self.assertIsNone(self.mod.observed_int(""))
        self.assertIsNone(self.mod.observed_int(None))
        self.assertEqual(self.mod.observed_int("0"), 0)
        self.assertEqual(self.mod.observed_int("评论 12"), 12)

    def test_comment_capture_has_network_reload_and_public_api_fallback(self):
        text = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("page.reload(", text)
        self.assertIn("/api/comment/list/", text)
        self.assertIn("fetch_public_comment_api", text)

    def test_active_runner_has_toutiao(self):
        runner = (ROOT / "run_single_platform.py").read_text(encoding="utf-8")
        final_policy = (ROOT / "monitor" / "final_realtime_policy.py").read_text(encoding="utf-8")
        self.assertIn('"toutiao"', runner)
        self.assertIn('"toutiao"', final_policy)

    def test_student_config_has_toutiao(self):
        text = (ROOT / "config" / "monitoring.student.windows.json").read_text(encoding="utf-8")
        self.assertIn('"toutiao"', text)
        self.assertIn("今日头条", text)
        self.assertEqual(text.count('"code": "toutiao"'), 1)


if __name__ == "__main__":
    unittest.main()
