from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WeiboCommentHierarchyPatchTest(unittest.TestCase):
    def test_patch_script_contract(self):
        text = (ROOT / "scripts" / "patch_weibo_comment_hierarchy.py").read_text(encoding="utf-8")
        self.assertIn("PROMOTION_WEEK_WB_COMMENT_HIERARCHY_V2", text)
        self.assertIn('["parent_comment_id"] = ""', text)
        self.assertIn('["root_comment_id"] = _promotion_week_wb_root_id', text)
        self.assertIn('async def get_note_sub_comments_page(', text)
        self.assertIn('"/comments/hotFlowChild"', text)
        self.assertIn("seen_ids = set()", text)
        self.assertIn("child pagination guard reached", text)
        self.assertIn('"parent_comment_id": str(comment_item.get("parent_comment_id") or "")', text)
        self.assertIn('"root_comment_id": str(comment_item.get("root_comment_id") or comment_id)', text)


if __name__ == "__main__":
    unittest.main()
