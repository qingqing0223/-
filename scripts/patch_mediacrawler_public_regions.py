from __future__ import annotations

import argparse
import ast
import json
import subprocess
from datetime import datetime
from pathlib import Path

PINNED_MEDIACRAWLER_COMMIT = "60e66f2a925816960bbd44af5d6c9b8385d79335"
PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4"
MARKER = PATCH_VERSION
TEMPLATE = Path(__file__).with_name("public_region_helper_template.py")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)


def ensure_import(text: str, anchor: str, line: str, label: str) -> str:
    return text if line in text else once(text, anchor, anchor + line, label)


def patch_direct_store(path: Path, import_anchor: str, import_line: str,
                       content_anchor: str, content_line: str,
                       comment_anchor: str, comment_line: str,
                       need_config: bool = False) -> None:
    text = read(path)
    if need_config and "\nimport config\n" not in text:
        text = once(text, "import re\n", "import re\nimport config\n", f"{path}: import config")
    text = ensure_import(text, import_anchor, import_line, f"{path}: public-region import")
    text = once(text, content_anchor, content_line + content_anchor, f"{path}: content region")
    text = once(text, comment_anchor, comment_line + comment_anchor, f"{path}: comment region")
    write_py(path, text)


def patch_douyin(root: Path) -> None:
    p = root / "store/douyin/__init__.py"
    text = read(p)

    old_import = f"from tools.public_region import coarse_public_region  # {MARKER}\n"
    new_import = f"from tools.public_region import coarse_public_region, first_coarse_public_region  # {MARKER}\n"
    if old_import in text:
        text = text.replace(old_import, new_import, 1)

    old_content = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = coarse_public_region(aweme_item.get("ip_label") or aweme_item.get("ip_location") or aweme_item.get("ip_region") or aweme_item.get("ipRegion") or aweme_item.get("region") or user_info.get("ip_location") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region"))\n'
    )
    old_comment = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_label") or comment_item.get("ip_location") or comment_item.get("ip_region") or comment_item.get("ipRegion") or comment_item.get("region") or user_info.get("ip_location") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region"))\n'
    )
    new_content = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_content_item["ip_location"] = first_coarse_public_region('
        'aweme_item.get("ip_label"), aweme_item.get("ip_location"), aweme_item.get("ip_region"), '
        'aweme_item.get("ipRegion"), aweme_item.get("region"), user_info.get("ip_location"), '
        'user_info.get("ip_label"), user_info.get("ip_region"), user_info.get("ipRegion"), user_info.get("region"))\n'
    )
    new_comment = (
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n'
        '        save_comment_item["ip_location"] = first_coarse_public_region('
        'comment_item.get("ip_label"), comment_item.get("ip_location"), comment_item.get("ip_region"), '
        'comment_item.get("ipRegion"), comment_item.get("region"), user_info.get("ip_location"), '
        'user_info.get("ip_label"), user_info.get("ip_region"), user_info.get("ipRegion"), user_info.get("region"))\n'
    )
    text = text.replace(old_content, new_content).replace(old_comment, new_comment)
    write_py(p, text)

    patch_direct_store(
        p,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        new_import,
        '    utils.logger.info(f"[store.douyin.update_douyin_aweme] douyin aweme id:{aweme_id}, title:{save_content_item.get(\'title\')}")\n',
        new_content,
        '    utils.logger.info(f"[store.douyin.update_dy_aweme_comment] douyin aweme comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        new_comment,
    )

def patch_xhs(root: Path) -> None:
    p = root / "store/xhs/__init__.py"
    patch_direct_store(
        p,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        '    utils.logger.info(f"[store.xhs.update_xhs_note] xhs note: {local_db_item}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        local_db_item["ip_location"] = coarse_public_region(note_item.get("ip_location") or note_item.get("ipLocation") or note_item.get("ip_label") or note_item.get("ip_region") or note_item.get("ipRegion") or note_item.get("region") or note_item.get("region_name") or user_info.get("ip_location") or user_info.get("ipLocation") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region") or user_info.get("region_name"))\n',
        '    utils.logger.info(f"[store.xhs.update_xhs_note_comment] xhs note comment:{local_db_item}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        local_db_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("ipLocation") or comment_item.get("ip_label") or comment_item.get("ip_region") or comment_item.get("ipRegion") or comment_item.get("region") or comment_item.get("region_name") or user_info.get("ip_location") or user_info.get("ipLocation") or user_info.get("ip_label") or user_info.get("ip_region") or user_info.get("ipRegion") or user_info.get("region") or user_info.get("region_name"))\n',
    )


def patch_weibo(root: Path) -> None:
    p = root / "store/weibo/__init__.py"
    patch_direct_store(
        p,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        '    utils.logger.info(f"[store.weibo.update_weibo_note] weibo note id:{note_id}, title:{save_content_item.get(\'content\')[:24]} ...")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_content_item["ip_location"] = coarse_public_region(mblog.get("ip_location") or mblog.get("region_name") or mblog.get("ip_region") or user_info.get("ip_location") or user_info.get("region_name") or user_info.get("ip_region"))\n',
        '    utils.logger.info(f"[store.weibo.update_weibo_note_comment] Weibo note comment: {comment_id}, content: {save_comment_item.get(\'content\', \'\')[:24]} ...")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("region_name") or comment_item.get("ip_region") or user_info.get("ip_location") or user_info.get("region_name") or user_info.get("ip_region"))\n',
        need_config=True,
    )


def patch_kuaishou(root: Path) -> None:
    p = root / "store/kuaishou/__init__.py"
    patch_direct_store(
        p,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        '    utils.logger.info(\n        f"[store.kuaishou.update_kuaishou_video] Kuaishou video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_content_item["ip_location"] = coarse_public_region(photo_info.get("ip_location") or photo_info.get("ipRegion") or photo_info.get("ip_region") or photo_info.get("region") or video_item.get("ip_location") or video_item.get("ipRegion") or video_item.get("ip_region") or video_item.get("region") or user_info.get("ip_location") or user_info.get("ipRegion") or user_info.get("ip_region"))\n',
        '    utils.logger.info(\n        f"[store.kuaishou.update_ks_video_comment] Kuaishou video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_location") or comment_item.get("ipRegion") or comment_item.get("ip_region") or comment_item.get("region") or (comment_item.get("user") or {{}}).get("ip_location") or (comment_item.get("user") or {{}}).get("ipRegion") or (comment_item.get("user") or {{}}).get("ip_region"))\n',
    )


def patch_bilibili(root: Path) -> None:
    p = root / "store/bilibili/__init__.py"
    patch_direct_store(
        p,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        f"from tools.public_region import coarse_public_region  # {MARKER}\n",
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video] bilibili video id:{video_id}, title:{save_content_item.get(\'title\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_content_item["ip_location"] = coarse_public_region(video_item_view.get("pub_location") or video_item_view.get("ip_location") or video_item_view.get("ip_region") or video_user_info.get("ip_location") or video_user_info.get("ip_region"))\n',
        '    utils.logger.info(f"[store.bilibili.update_bilibili_video_comment] Bilibili video comment: {comment_id}, content: {save_comment_item.get(\'content\')}")\n',
        f'    if config.SAVE_DATA_OPTION == "jsonl":  # {MARKER}\n        save_comment_item["ip_location"] = coarse_public_region((comment_item.get("reply_control") or {{}}).get("location") or comment_item.get("ip_location") or comment_item.get("ip_region") or (comment_item.get("member") or {{}}).get("ip_location") or (comment_item.get("member") or {{}}).get("ip_region"))\n',
    )


def patch_tieba(root: Path) -> None:
    model = root / "model/m_baidu_tieba.py"
    text = read(model)
    anchor = '    publish_time: str = Field(default="", description="Publish time")\n'
    if MARKER not in text:
        if text.count(anchor) != 2:
            raise RuntimeError(f"{model}: expected two publish_time anchors, found {text.count(anchor)}")
        text = text.replace(anchor, anchor + f'    ip_location: str = Field(default="", description="Coarse public IP-location label")  # {MARKER}\n', 2)
    write_py(model, text)

    helper = root / "media_platform/tieba/help.py"
    text = read(helper)
    text = ensure_import(text, "from tools.user_hash import anonymize_user_id, mask_nickname\n", f"from tools.public_region import coarse_public_region  # {MARKER}\n", "tieba import")
    text = once(text,
        '                user_nickname=mask_nickname(user.get("show_nickname") or user.get("user_name") or ""),\n                tieba_name=tieba_name,\n',
        '                user_nickname=mask_nickname(user.get("show_nickname") or user.get("user_name") or ""),\n                ip_location=coarse_public_region(item.get("ip_address") or item.get("ip_location") or item.get("ip_region") or user.get("ip_address") or user.get("ip_location") or user.get("ip_region")),\n                tieba_name=tieba_name,\n', "tieba api search note")
    text = once(text,
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n            tieba_name=tieba_name,\n',
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n            ip_location=coarse_public_region(first_floor.get("ip_address") or first_floor.get("ip_location") or first_floor.get("ip_region") or thread.get("ip_address") or thread.get("ip_location") or thread.get("ip_region") or author.get("ip_address") or author.get("ip_location") or author.get("ip_region")),\n            tieba_name=tieba_name,\n', "tieba api note")
    text = once(text,
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n                tieba_id=tieba_id,\n',
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n                ip_location=coarse_public_region(item.get("ip_address") or item.get("ip_location") or item.get("ip_region") or user.get("ip_address") or user.get("ip_location") or user.get("ip_region")),\n                tieba_id=tieba_id,\n', "tieba api comment")
    text = once(text, '            publish_time=publish_time,\n            total_replay_num=(\n', '            publish_time=publish_time,\n            ip_location=coarse_public_region(ip_location),\n            total_replay_num=(\n', "tieba html note")
    text = once(text, '                publish_time=publish_time,\n                note_id=note_id,\n', '                publish_time=publish_time,\n                ip_location=coarse_public_region(ip_location),\n                note_id=note_id,\n', "tieba html comment")
    text = once(text,
        '                user_nickname=mask_nickname(str(comment_value.get("showname") or "")),\n                publish_time=self._selector_text(comment_ele, f".//span[{self._class_contains(\'lzl_time\')}]"),\n',
        '                user_nickname=mask_nickname(str(comment_value.get("showname") or "")),\n                ip_location=coarse_public_region(comment_value.get("ip_address") or comment_value.get("ip_location") or comment_value.get("ip_region") or comment_value.get("region")),\n                publish_time=self._selector_text(comment_ele, f".//span[{self._class_contains(\'lzl_time\')}]"),\n', "tieba html sub-comment region")
    write_py(helper, text)

    store = root / "store/tieba/__init__.py"
    text = read(store)
    if "\nimport config\n" not in text:
        text = once(text, "from typing import List\n\n", "from typing import List\n\nimport config\n\n", "tieba config import")
    text = once(text,
        '    save_note_item = note_item.model_dump()\n    save_note_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    save_note_item = note_item.model_dump()\n' + f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n' + '        save_note_item.pop("ip_location", None)\n    save_note_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', "tieba note guard")
    text = once(text,
        '    save_comment_item = comment_item.model_dump()\n    save_comment_item.update({"last_modify_ts": utils.get_current_timestamp()})\n',
        '    save_comment_item = comment_item.model_dump()\n' + f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n' + '        save_comment_item.pop("ip_location", None)\n    save_comment_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', "tieba comment guard")
    write_py(store, text)


def patch_zhihu(root: Path) -> None:
    model = root / "model/m_zhihu.py"
    text = read(model)
    a = '    source_keyword: str = Field(default="", description="Source keyword")\n    creator_hash: str = Field(default="", description="Creator anonymized hash")\n    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    text = once(text, a, a + f'    ip_location: str = Field(default="", description="Coarse public IP-location label")  # {MARKER}\n', "zhihu content model")
    b = '    content_type: str = Field(default="", description="Content type (article | answer | zvideo)")\n    creator_hash: str = Field(default="", description="Creator anonymized hash")\n    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    text = once(text, b, b + '    ip_location: str = Field(default="", description="Coarse public IP-location label")\n', "zhihu comment model")
    write_py(model, text)

    helper = root / "media_platform/zhihu/help.py"
    text = read(helper)
    text = ensure_import(text, "from tools.user_hash import anonymize_user_id, mask_nickname\n", f"from tools.public_region import coarse_public_region  # {MARKER}\n", "zhihu import")
    text = once(text, '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    def _extract_article_content', '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        res.ip_location = coarse_public_region(answer.get("ip_location") or answer.get("ip_region") or (answer.get("author") or {}).get("ip_location") or (answer.get("author") or {}).get("ip_region"))\n        return res\n\n    def _extract_article_content', "zhihu answer")
    text = once(text, '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    def _extract_zvideo_content', '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        res.ip_location = coarse_public_region(article.get("ip_location") or article.get("ip_region") or (article.get("author") or {}).get("ip_location") or (article.get("author") or {}).get("ip_region"))\n        return res\n\n    def _extract_zvideo_content', "zhihu article")
    text = once(text, '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    @staticmethod\n    def _extract_content_or_comment_author', '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        res.ip_location = coarse_public_region(zvideo.get("ip_location") or zvideo.get("ip_region") or (zvideo.get("author") or {}).get("ip_location") or (zvideo.get("author") or {}).get("ip_region"))\n        return res\n\n    @staticmethod\n    def _extract_content_or_comment_author', "zhihu video")
    text = once(text, '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        return res\n\n    @staticmethod\n    def _extract_comment_ip_location', '        res.creator_hash = author_info.creator_hash\n        res.user_nickname = author_info.user_nickname\n        res.ip_location = coarse_public_region(comment.get("ip_location") or comment.get("ip_region") or self._extract_comment_ip_location(comment.get("comment_tag") or comment.get("comment_tags") or []))\n        return res\n\n    @staticmethod\n    def _extract_comment_ip_location', "zhihu comment")
    write_py(helper, text)

    store = root / "store/zhihu/__init__.py"
    text = read(store)
    text = once(text, '    local_db_item = content_item.model_dump()\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', '    local_db_item = content_item.model_dump()\n' + f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n' + '        local_db_item.pop("ip_location", None)\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', "zhihu content guard")
    text = once(text, '    local_db_item = comment_item.model_dump()\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', '    local_db_item = comment_item.model_dump()\n' + f'    if config.SAVE_DATA_OPTION != "jsonl":  # {MARKER}\n' + '        local_db_item.pop("ip_location", None)\n    local_db_item.update({"last_modify_ts": utils.get_current_timestamp()})\n', "zhihu comment guard")
    write_py(store, text)


def files(root: Path) -> dict[str, Path]:
    return {
        "dy": root / "store/douyin/__init__.py", "xhs": root / "store/xhs/__init__.py",
        "wb": root / "store/weibo/__init__.py", "ks": root / "store/kuaishou/__init__.py",
        "bili": root / "store/bilibili/__init__.py", "tieba_model": root / "model/m_baidu_tieba.py",
        "tieba_helper": root / "media_platform/tieba/help.py", "tieba_store": root / "store/tieba/__init__.py",
        "zhihu_model": root / "model/m_zhihu.py", "zhihu_helper": root / "media_platform/zhihu/help.py",
        "zhihu_store": root / "store/zhihu/__init__.py",
    }


def git_head(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def check(root: Path) -> dict:
    status = {}
    for name, p in files(root).items():
        try:
            text = read(p); ast.parse(text, filename=str(p)); status[name] = MARKER in text
        except Exception:
            status[name] = False
    hp = root / "tools/public_region.py"
    try:
        ht = read(hp); ast.parse(ht, filename=str(hp)); helper_ok = "def coarse_public_region" in ht
    except Exception:
        helper_ok = False
    head = git_head(root)
    return {"ok": helper_ok and all(status.values()) and head == PINNED_MEDIACRAWLER_COMMIT,
            "version": PATCH_VERSION, "pinned_commit_expected": PINNED_MEDIACRAWLER_COMMIT,
            "media_crawler_head": head, "pinned_commit_ok": head == PINNED_MEDIACRAWLER_COMMIT,
            "helper_ok": helper_ok, "source_patch": status,
            "privacy": "coarse_public_region_only_no_real_ip_no_precise_location"}


def apply(root: Path) -> dict:
    missing = [str(p) for p in [root / "main.py", TEMPLATE, *files(root).values()] if not p.exists()]
    if missing:
        raise RuntimeError("required source missing: " + " | ".join(missing))
    helper = root / "tools/public_region.py"
    helper.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    ast.parse(read(helper), filename=str(helper))
    for fn in (patch_douyin, patch_xhs, patch_weibo, patch_kuaishou, patch_bilibili, patch_tieba, patch_zhihu):
        fn(root)
    report = check(root)
    (root / ".promotion_week_public_region_patch.json").write_text(json.dumps({"version": PATCH_VERSION, "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"), **report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch pinned MediaCrawler to retain coarse platform-displayed IP-region labels in JSONL output.")
    ap.add_argument("--root", required=True); ap.add_argument("--check", action="store_true")
    args = ap.parse_args(); root = Path(args.root).resolve()
    try:
        report = check(root) if args.check else apply(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "version": PATCH_VERSION, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2)); return 2
    print(json.dumps({"root": str(root), **report}, ensure_ascii=False, indent=2)); return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
