from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import patch_bilibili_data_fields as patch


STORE = '''from typing import Dict, List
import config
from var import source_keyword_var
from tools.user_hash import anonymize_user_id, mask_nickname

async def update_bilibili_video(video_item: Dict):
    video_item_view: Dict = video_item.get("View")
    video_user_info: Dict = video_item_view.get("owner")
    video_item_stat: Dict = video_item_view.get("stat")
    video_id = str(video_item_view.get("aid"))
    save_content_item = {
        "video_id": video_id,
        "video_type": "video",
        "title": video_item_view.get("title", "")[:500],
        "desc": video_item_view.get("desc", "")[:500],
        "create_time": video_item_view.get("pubdate"),
        "creator_hash": anonymize_user_id(video_user_info.get("mid")),
        "nickname": mask_nickname(video_user_info.get("name")),
        "liked_count": str(video_item_stat.get("like", "")),
        "disliked_count": str(video_item_stat.get("dislike", "")),
        "video_play_count": str(video_item_stat.get("view", "")),
        "video_favorite_count": str(video_item_stat.get("favorite", "")),
        "video_share_count": str(video_item_stat.get("share", "")),
        "video_coin_count": str(video_item_stat.get("coin", "")),
        "video_danmaku": str(video_item_stat.get("danmaku", "")),
        "video_comment": str(video_item_stat.get("reply", "")),
        "last_modify_ts": 0,
        "video_url": f"https://www.bilibili.com/video/av{video_id}",
        "video_cover_url": video_item_view.get("pic", ""),
        "source_keyword": source_keyword_var.get(),
    }
    utils.logger.info(f"[store.bilibili.update_bilibili_video] bilibili video id:{video_id}, title:{save_content_item.get('title')}")

async def update_bilibili_video_comment(video_id: str, comment_item: Dict):
    comment_id = str(comment_item.get("rpid"))
    parent_comment_id = str(comment_item.get("parent", 0))
    content: Dict = comment_item.get("content")
    user_info: Dict = comment_item.get("member")
    like_count: int = comment_item.get("like", 0)
    save_comment_item = {
        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id,
        "create_time": comment_item.get("ctime"),
        "video_id": str(video_id),
        "content": content.get("message"),
        "creator_hash": anonymize_user_id(user_info.get("mid")),
        "nickname": mask_nickname(user_info.get("uname")),
        "sub_comment_count": str(comment_item.get("rcount", 0)),
        "like_count": like_count,
        "last_modify_ts": 0,
    }
    utils.logger.info(f"[store.bilibili.update_bilibili_video_comment] Bilibili video comment: {comment_id}, content: {save_comment_item.get('content')}")
'''


class BilibiliDataFieldsPatchTests(unittest.TestCase):
    def test_patch_is_idempotent_and_preserves_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "store" / "bilibili"
            target.mkdir(parents=True)
            store = target / "__init__.py"
            store.write_text(STORE, encoding="utf-8")

            patch.patch_store(root)
            first = store.read_text(encoding="utf-8")
            patch.patch_store(root)
            second = store.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            ast.parse(first)
            result = patch.check(root)
            self.assertTrue(result["ok"])

            for token in (
                '"bvid":',
                '"category_name":',
                '"duration":',
                '"tags": _bili_tags',
                '"creator_public_id":',
                '"account_name":',
                '"creator_profile_url":',
                '"follower_count":',
                '"following_count":',
                '"creator_official_title":',
                '"root_comment_id": str(comment_item.get("root", 0))',
            ):
                self.assertIn(token, first)


if __name__ == "__main__":
    unittest.main()
