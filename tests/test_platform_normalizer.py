from __future__ import annotations

import unittest

from pipeline.normalizer import normalize_record


class PlatformNormalizerTests(unittest.TestCase):
    def test_bilibili_video_fields(self):
        raw = {
            "video_id": "12345",
            "video_type": "video",
            "title": "民族团结进步宣传周",
            "desc": "示例视频",
            "create_time": 1757971200,
            "nickname": "示例UP主",
            "liked_count": "88",
            "video_comment": "12",
            "video_share_count": "7",
            "video_play_count": "1000",
            "video_favorite_count": "30",
            "video_danmaku": "9",
            "video_coin_count": "15",
            "video_url": "https://www.bilibili.com/video/av12345",
            "source_keyword": "民族团结进步宣传周",
        }
        row = normalize_record(raw, source_file="search_contents.jsonl", platform_hint="bili")
        self.assertIsNotNone(row)
        self.assertEqual(row["platform"], "bili")
        self.assertEqual(row["record_type"], "video")
        self.assertEqual(row["sample_id"], "12345")
        self.assertEqual(row["likes"], 88)
        self.assertEqual(row["comments"], 12)
        self.assertEqual(row["shares"], 7)
        self.assertEqual(row["views"], 1000)
        self.assertEqual(row["favorites"], 30)
        self.assertEqual(row["danmaku"], 9)
        self.assertEqual(row["coins"], 15)

    def test_zhihu_article_fields(self):
        raw = {
            "content_id": "answer-001",
            "content_type": "answer",
            "content_text": "这是一条知乎回答正文",
            "content_url": "https://www.zhihu.com/question/1/answer/2",
            "title": "宣传周相关讨论",
            "created_time": 1757971200,
            "voteup_count": 66,
            "comment_count": 8,
            "user_nickname": "示例用户",
            "source_keyword": "民族团结进步宣传周",
        }
        row = normalize_record(raw, source_file="search_contents.jsonl", platform_hint="zhihu")
        self.assertIsNotNone(row)
        self.assertEqual(row["record_type"], "post")
        self.assertEqual(row["url"], raw["content_url"])
        self.assertEqual(row["likes"], 66)
        self.assertEqual(row["comments"], 8)
        self.assertTrue(row["publish_time"])

    def test_zhihu_zvideo_is_video(self):
        raw = {
            "content_id": "zvideo-001",
            "content_type": "zvideo",
            "title": "知乎视频",
            "desc": "视频简介",
            "created_time": 1757971200,
        }
        row = normalize_record(raw, platform_hint="zhihu")
        self.assertEqual(row["record_type"], "video")

    def test_toutiao_article_fields(self):
        raw = {
            "article_id": "9988",
            "content_id": "9988",
            "content_type": "article",
            "title": "宣传周相关报道",
            "content_text": "今日头条文章正文摘要",
            "content_url": "https://www.toutiao.com/article/9988/",
            "publish_time": "2026-09-16 09:00:00",
            "author": "示例头条号",
            "comment_count": 23,
            "like_count": 12,
            "source_keyword": "民族团结进步宣传周",
        }
        row = normalize_record(raw, source_file="search_contents.jsonl", platform_hint="toutiao")
        self.assertIsNotNone(row)
        self.assertEqual(row["record_type"], "post")
        self.assertEqual(row["sample_id"], "9988")
        self.assertEqual(row["comments"], 23)
        self.assertEqual(row["likes"], 12)
        self.assertEqual(row["url"], raw["content_url"])

    def test_comment_hierarchy_and_public_author_fields(self):
        raw = {
            "comment_id": "c-child",
            "parent_comment_id": "c-root",
            "note_id": "n-001",
            "content": "这是一条楼中楼回复",
            "nickname": "示例评论者",
            "creator_hash": "hashed-author",
            "ip_location": "北京",
            "create_time": 1757971200,
            "like_count": "9",
            "sub_comment_count": 2,
        }
        row = normalize_record(raw, source_file="comments.jsonl", platform_hint="xhs")
        self.assertIsNotNone(row)
        self.assertEqual(row["record_type"], "comment")
        self.assertEqual(row["comment_id"], "c-child")
        self.assertEqual(row["parent_comment_id"], "c-root")
        self.assertEqual(row["root_comment_id"], "c-root")
        self.assertEqual(row["comment_level"], 2)
        self.assertEqual(row["author_id"], "hashed-author")
        self.assertEqual(row["ip_location"], "北京")
        self.assertEqual(row["likes"], 9)
        self.assertEqual(row["sub_comment_count"], 2)


if __name__ == "__main__":
    unittest.main()
