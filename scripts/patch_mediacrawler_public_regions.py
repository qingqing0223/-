from __future__ import annotations

import argparse
import ast
import json
import subprocess
from datetime import datetime
from pathlib import Path

PINNED_MEDIACRAWLER_COMMIT = "60e66f2a925816960bbd44af5d6c9b8385d79335"
PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V2"
MARKER = PATCH_VERSION

PUBLIC_REGION_HELPER = r"""# -*- coding: utf-8 -*-
\"\"\"Keep only coarse public IP-location labels exposed by a platform.

This helper never derives or stores a real IP address or precise location.
It accepts labels such as ``IP属地：山东`` / ``北京`` and rejects IP-looking
values, coordinates and long address-like strings.
\"\"\"
from __future__ import annotations
import re

_PROVINCES = (
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
)
_IP_LIKE = re.compile(r"^(?:\\d{1,3}\\.){3}\\d{1,3}$|^[0-9a-fA-F:]{6,}$")


def coarse_public_region(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for prefix in ("IP属地：", "IP属地:", "IP属地", "来自：", "来自:", "来自"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if not text or _IP_LIKE.fullmatch(text):
        return ""
    for province in _PROVINCES:
        if province in text:
            return province
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def _write_checked(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 anchor, found {count}")
    return text.replace(old, new, 1)


def _patch_douyin(root: Path) -> None:
    p = root / "store" / "douyin" / "__init__.py"
    text = _read(p)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "douyin import",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.douyin.update_douyin_aweme] douyin aweme id:{aweme_id}, title:{save_content_item.get(\'title\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = coarse_public_region(aweme_item.get("ip_label"))\n'
        '    utils.logger.info(f"[store.douyin.update_douyin_aweme] douyin aweme id:{aweme_id}, title:{save_content_item.get(\'title\')}")\n',
        "douyin content region",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.douyin.update_dy_aweme_comment] douyin aweme comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_label"))\n'
        '    utils.logger.info(f"[store.douyin.update_dy_aweme_comment] douyin aweme comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        "douyin comment region",
    )
    _write_checked(p, text)


def _patch_xhs(root: Path) -> None:
    p = root / "store" / "xhs" / "__init__.py"
    text = _read(p)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "xhs import",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.xhs.update_xhs_note] xhs note: {local_db_item}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        local_db_item["ip_location"] = coarse_public_region(note_item.get("ip_location") or note_item.get("ip_label"))\n'
        '    utils.logger.info(f"[store.xhs.update_xhs_note] xhs note: {local_db_item}")\n',
        "xhs content region",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.xhs.update_xhs_note_comment] xhs note comment:{local_db_item}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        local_db_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("ip_label"))\n'
        '    utils.logger.info(f"[store.xhs.update_xhs_note_comment] xhs note comment:{local_db_item}")\n',
        "xhs comment region",
    )
    _write_checked(p, text)


def _patch_weibo(root: Path) -> None:
    p = root / "store" / "weibo" / "__init__.py"
    text = _read(p)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "weibo import",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.weibo.update_weibo_note] weibo note id:{note_id}, title:{save_content_item.get(\'content\')[:24]} ...")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = coarse_public_region(mblog.get("ip_location") or mblog.get("region_name") or user_info.get("ip_location"))\n'
        '    utils.logger.info(f"[store.weibo.update_weibo_note] weibo note id:{note_id}, title:{save_content_item.get(\'content\')[:24]} ...")\n',
        "weibo content region",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.weibo.update_weibo_note_comment] Weibo note comment: {comment_id}, content: {save_comment_item.get(\'content\', \'\')[:24]} ...")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("region_name") or user_info.get("ip_location"))\n'
        '    utils.logger.info(f"[store.weibo.update_weibo_note_comment] Weibo note comment: {comment_id}, content: {save_comment_item.get(\'content\', \'\')[:24]} ...")\n',
        "weibo comment region",
    )
    _write_checked(p, text)


def _patch_kuaishou(root: Path) -> None:
    p = root / "store" / "kuaishou" / "__init__.py"
    text = _read(p)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "kuaishou import",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(\n        f"[store.kuaishou.update_kuaishou_video] Kuaishou video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = coarse_public_region(photo_info.get("ip_location") or photo_info.get("ipRegion") or photo_info.get("region") or video_item.get("ip_location") or video_item.get("ipRegion") or video_item.get("region") or user_info.get("ip_location") or user_info.get("ipRegion"))\n'
        '    utils.logger.info(\n'
        '        f"[store.kuaishou.update_kuaishou_video] Kuaishou video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        "kuaishou content region",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(\n        f"[store.kuaishou.update_ks_video_comment] Kuaishou video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("ipRegion") or comment_item.get("region"))\n'
        '    utils.logger.info(\n'
        '        f"[store.kuaishou.update_ks_video_comment] Kuaishou video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        "kuaishou comment region",
    )
    _write_checked(p, text)


def _patch_bilibili(root: Path) -> None:
    p = root / "store" / "bilibili" / "__init__.py"
    text = _read(p)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "bilibili import",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video] bilibili video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = coarse_public_region(video_item_view.get("pub_location") or video_item_view.get("ip_location") or video_user_info.get("ip_location"))\n'
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video] bilibili video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        "bilibili content region",
    )
    text = _replace_once(
        text,
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video_comment] Bilibili video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = coarse_public_region((comment_item.get("reply_control") or {}).get("location") or comment_item.get("ip_location"))\n'
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video_comment] Bilibili video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        "bilibili comment region",
    )
    _write_checked(p, text)


def _patch_tieba(root: Path) -> None:
    model = root / "model" / "m_baidu_tieba.py"
    text = _read(model)
    anchor = '    publish_time: str = Field(default="", description="Publish time")\n'
    if MARKER not in text:
        if text.count(anchor) != 2:
            raise RuntimeError(f"tieba model: expected 2 publish_time anchors, found {text.count(anchor)}")
        text = text.replace(anchor, anchor + f'    ip_location: str = Field(default="", description="Coarse public IP-location label")  # {MARKER}\n', 2)
    _write_checked(model, text)

    helper = root / "media_platform" / "tieba" / "help.py"
    text = _read(helper)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "tieba import",
    )
    text = _replace_once(
        text,
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n            tieba_name=tieba_name,\n',
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n'
        '            ip_location=coarse_public_region(author.get("ip_address") or author.get("ip_location")),\n'
        '            tieba_name=tieba_name,\n',
        "tieba api note region",
    )
    text = _replace_once(
        text,
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n                tieba_id=tieba_id,\n',
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n'
        '                ip_location=coarse_public_region(user.get("ip_address") or user.get("ip_location")),\n'
        '                tieba_id=tieba_id,\n',
        "tieba api comment region",
    )
    text = _replace_once(
        text,
        '            publish_time=publish_time,\n            total_replay_num=(\n',
        '            publish_time=publish_time,\n            ip_location=coarse_public_region(ip_location),\n            total_replay_num=(\n',
        "tieba html note region",
    )
    text = _replace_once(
        text,
        '                publish_time=publish_time,\n                note_id=note_id,\n',
        '                publish_time=publish_time,\n                ip_location=coarse_public_region(ip_location),\n                note_id=note_id,\n',
        "tieba html comment region",
    )
    _write_checked(helper, text)

    store = root / "store" / "tieba" / "__init__.py"
    text = _read(store)
    if "\nimport config\n" not in text:
        text = _replace_once(text, "from typing import List\n\n", "from typing import List\n\nimport config\n\n", "tieba import config")
    text = _replace_once(
        text,
        '    save_note_item = note_item.model_dump()\n    save_note_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    save_note_item = note_item.model_dump()\n'
        f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n'
        '        save_note_item.pop("ip_location", None)\n'
        '    save_note_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        "tieba note store guard",
    )
    text = _replace_once(
        text,
        '    save_comment_item = comment_item.model_dump()\n    save_comment_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    save_comment_item = comment_item.model_dump()\n'
        f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n'
        '        save_comment_item.pop("ip_location", None)\n'
        '    save_comment_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        "tieba comment store guard",
    )
    _write_checked(store, text)


def _patch_zhihu(root: Path) -> None:
    model = root / "model" / "m_zhihu.py"
    text = _read(model)
    content_anchor = (
        '    source_keyword: str = Field(default="", description="Source keyword")\n'
        '    creator_hash: str = Field(default="", description="Creator anonymized hash")\n'
        '    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    )
    text = _replace_once(
        text,
        content_anchor,
        content_anchor + f'    ip_location: str = Field(default="", description="Coarse public IP-location label")  # {MARKER}\n',
        "zhihu content model region",
    )
    comment_anchor = (
        '    content_type: str = Field(default="", description="Content type (article | answer | zvideo)")\n'
        '    creator_hash: str = Field(default="", description="Creator anonymized hash")\n'
        '    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    )
    text = _replace_once(
        text,
        comment_anchor,
        comment_anchor + '    ip_location: str = Field(default="", description="Coarse public IP-location label")\n',
        "zhihu comment model region",
    )
    _write_checked(model, text)

    helper = root / "media_platform" / "zhihu" / "help.py"
    text = _read(helper)
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\n"
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        "zhihu import",
    )
    text = _replace_once(
        text,
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    def _extract_article_content',
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n'
        '        res.ip_location = coarse_public_region(answer.get("ip_location") or (answer.get("author") or {}).get("ip_location"))\n'
        '        return res\n\n    def _extract_article_content',
        "zhihu answer region",
    )
    text = _replace_once(
        text,
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    def _extract_zvideo_content',
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n'
        '        res.ip_location = coarse_public_region(article.get("ip_location") or (article.get("author") or {}).get("ip_location"))\n'
        '        return res\n\n    def _extract_zvideo_content',
        "zhihu article region",
    )
    text = _replace_once(
        text,
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    @staticmethod\n    def _extract_content_or_comment_author',
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n'
        '        res.ip_location = coarse_public_region(zvideo.get("ip_location") or (zvideo.get("author") or {}).get("ip_location"))\n'
        '        return res\n\n    @staticmethod\n    def _extract_content_or_comment_author',
        "zhihu video region",
    )
    text = _replace_once(
        text,
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    @staticmethod\n    def _extract_comment_ip_location',
        '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n'
        '        res.ip_location = coarse_public_region(self._extract_comment_ip_location(comment.get("comment_tag") or comment.get("comment_tags") or []))\n'
        '        return res\n\n    @staticmethod\n    def _extract_comment_ip_location',
        "zhihu comment region",
    )
    _write_checked(helper, text)

    store = root / "store" / "zhihu" / "__init__.py"
    text = _read(store)
    text = _replace_once(
        text,
        '    local_db_item = content_item.model_dump()\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    local_db_item = content_item.model_dump()\n'
        f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n'
        '        local_db_item.pop("ip_location", None)\n'
        '    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        "zhihu content store guard",
    )
    text = _replace_once(
        text,
        '    local_db_item = comment_item.model_dump()\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    local_db_item = comment_item.model_dump()\n'
        f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n'
        '        local_db_item.pop("ip_location", None)\n'
        '    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        "zhihu comment store guard",
    )
    _write_checked(store, text)


def _source_files(root: Path) -> dict[str, Path]:
    return {
        "dy": root / "store" / "douyin" / "__init__.py",
        "xhs": root / "store" / "xhs" / "__init__.py",
        "wb": root / "store" / "weibo" / "__init__.py",
        "ks": root / "store" / "kuaishou" / "__init__.py",
        "bili": root / "store" / "bilibili" / "__init__.py",
        "tieba_model": root / "model" / "m_baidu_tieba.py",
        "tieba_helper": root / "media_platform" / "tieba" / "help.py",
        "tieba_store": root / "store" / "tieba" / "__init__.py",
        "zhihu_model": root / "model" / "m_zhihu.py",
        "zhihu_helper": root / "media_platform" / "zhihu" / "help.py",
        "zhihu_store": root / "store" / "zhihu" / "__init__.py",
    }


def check_all(root: Path) -> dict:
    status = {}
    for label, path in _source_files(root).items():
        try:
            text = _read(path)
            ast.parse(text, filename=str(path))
            status[label] = MARKER in text
        except Exception:
            status[label] = False

    helper = root / "tools" / "public_region.py"
    try:
        htext = _read(helper)
        ast.parse(htext, filename=str(helper))
        helper_ok = "def coarse_public_region" in htext
    except Exception:
        helper_ok = False

    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            text=True, capture_output=True, timeout=10,
        ).stdout.strip()
    except Exception:
        head = ""

    return {
        "ok": helper_ok and all(status.values()) and head == PINNED_MEDIACRAWLER_COMMIT,
        "version": PATCH_VERSION,
        "privacy": "coarse_public_region_only_no_real_ip_no_precise_location",
        "pinned_commit_expected": PINNED_MEDIACRAWLER_COMMIT,
        "media_crawler_head": head,
        "pinned_commit_ok": head == PINNED_MEDIACRAWLER_COMMIT,
        "helper_ok": helper_ok,
        "source_patch": status,
    }


def apply_all(root: Path) -> dict:
    missing = [str(p) for p in list(_source_files(root).values()) + [root / "main.py"] if not p.exists()]
    if missing:
        raise RuntimeError("MediaCrawler source layout mismatch; missing: " + " | ".join(missing))

    helper = root / "tools" / "public_region.py"
    helper.write_text(PUBLIC_REGION_HELPER, encoding="utf-8")
    ast.parse(_read(helper), filename=str(helper))

    _patch_douyin(root)
    _patch_xhs(root)
    _patch_weibo(root)
    _patch_kuaishou(root)
    _patch_bilibili(root)
    _patch_tieba(root)
    _patch_zhihu(root)

    report = check_all(root)
    manifest = {
        "version": PATCH_VERSION,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "privacy": report["privacy"],
        "pinned_commit_expected": PINNED_MEDIACRAWLER_COMMIT,
        "media_crawler_head": report["media_crawler_head"],
        "source_patch": report["source_patch"],
    }
    (root / ".promotion_week_public_region_patch.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch pinned MediaCrawler to retain coarse public IP-region labels in JSONL output.")
    ap.add_argument("--root", required=True, help="Local MediaCrawler root containing main.py")
    ap.add_argument("--check", action="store_true", help="Verify pinned commit and public-region patch only")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not (root / "main.py").exists():
        raise SystemExit(f"MediaCrawler main.py not found under: {root}")

    try:
        report = check_all(root) if args.check else apply_all(root)
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "version": PATCH_VERSION, "root": str(root), "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False, indent=2,
        ))
        return 2

    print(json.dumps({"root": str(root), **report}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
