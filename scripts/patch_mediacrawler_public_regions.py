from __future__ import annotations

import argparse
import compileall
from datetime import datetime
import json
from pathlib import Path
import re

PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V1"
MARKER = PATCH_VERSION

PUBLIC_REGION_HELPER = r'''# -*- coding: utf-8 -*-
"""Keep only coarse public IP-location labels exposed by the platform.

This helper never derives or stores a real IP address or a precise location. It
accepts labels such as "IP属地：山东" / "北京" and rejects IP-looking values.
"""
from __future__ import annotations
import re

_PROVINCES = (
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
    "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
)
_IP_LIKE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]{6,}$")


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
    # Some platforms expose country/region labels rather than a province. Keep
    # only a short non-numeric public label; never keep coordinates or addresses.
    if len(text) <= 16 and not any(ch.isdigit() for ch in text):
        return text
    return ""
'''


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch anchor not found for {label}")
    return text.replace(old, new, 1)


def _patch_store_simple(path: Path, replacements: list[tuple[str, str, str]]) -> bool:
    text = _read(path)
    if MARKER in text:
        return False
    for old, new, label in replacements:
        text = _replace_once(text, old, new, f"{path}:{label}")
    _write(path, text)
    return True


def _patch_douyin(root: Path) -> bool:
    p = root / "store" / "douyin" / "__init__.py"
    return _patch_store_simple(p, [
        (
            "from tools.user_hash import anonymize_user_id, mask_nickname\n",
            "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "import",
        ),
        (
            '        "create_time": aweme_item.get("create_time"),\n',
            '        "create_time": aweme_item.get("create_time"),\n        "ip_location": coarse_public_region(aweme_item.get("ip_label")),\n',
            "content region",
        ),
        (
            '        "content": comment_item.get("text"),\n',
            '        "content": comment_item.get("text"),\n        "ip_location": coarse_public_region(comment_item.get("ip_label")),\n',
            "comment region",
        ),
    ])


def _patch_xhs(root: Path) -> bool:
    p = root / "store" / "xhs" / "__init__.py"
    return _patch_store_simple(p, [
        (
            "from tools.user_hash import anonymize_user_id, mask_nickname\n",
            "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "import",
        ),
        (
            '        "last_update_time": note_item.get("last_update_time", 0),  # Note last update time\n',
            '        "last_update_time": note_item.get("last_update_time", 0),  # Note last update time\n        "ip_location": coarse_public_region(note_item.get("ip_location") or note_item.get("ip_label")),\n',
            "content region",
        ),
        (
            '        "content": comment_item.get("content"),  # Comment content\n',
            '        "content": comment_item.get("content"),  # Comment content\n        "ip_location": coarse_public_region(comment_item.get("ip_location") or comment_item.get("ip_label")),\n',
            "comment region",
        ),
    ])


def _patch_weibo(root: Path) -> bool:
    p = root / "store" / "weibo" / "__init__.py"
    return _patch_store_simple(p, [
        (
            "from tools.user_hash import anonymize_user_id, mask_nickname\n",
            "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "import",
        ),
        (
            '        "create_date_time": str(utils.rfc2822_to_china_datetime(mblog.get("created_at"))),\n',
            '        "create_date_time": str(utils.rfc2822_to_china_datetime(mblog.get("created_at"))),\n        "ip_location": coarse_public_region(mblog.get("ip_location") or user_info.get("ip_location")),\n',
            "content region",
        ),
        (
            '        "content": clean_text,\n        "sub_comment_count": str(comment_item.get("total_number", 0)),\n',
            '        "content": clean_text,\n        "ip_location": coarse_public_region(comment_item.get("ip_location") or user_info.get("ip_location")),\n        "sub_comment_count": str(comment_item.get("total_number", 0)),\n',
            "comment region",
        ),
    ])


def _patch_kuaishou(root: Path) -> bool:
    p = root / "store" / "kuaishou" / "__init__.py"
    return _patch_store_simple(p, [
        (
            "from tools.user_hash import anonymize_user_id, mask_nickname\n",
            "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "import",
        ),
        (
            '        "create_time": photo_info.get("timestamp"),\n',
            '        "create_time": photo_info.get("timestamp"),\n        "ip_location": coarse_public_region(photo_info.get("ip_location") or photo_info.get("ipRegion") or video_item.get("ip_location") or video_item.get("ipRegion") or video_item.get("region")),\n',
            "content region",
        ),
        (
            '        "content": comment_item.get("content"),\n',
            '        "content": comment_item.get("content"),\n        "ip_location": coarse_public_region(comment_item.get("ip_location") or comment_item.get("ipRegion") or comment_item.get("region")),\n',
            "comment region",
        ),
    ])


def _patch_bilibili(root: Path) -> bool:
    p = root / "store" / "bilibili" / "__init__.py"
    return _patch_store_simple(p, [
        (
            "from tools.user_hash import anonymize_user_id, mask_nickname\n",
            "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
            "import",
        ),
        (
            '        "create_time": video_item_view.get("pubdate"),\n',
            '        "create_time": video_item_view.get("pubdate"),\n        "ip_location": coarse_public_region(video_item_view.get("pub_location") or video_item_view.get("ip_location")),\n',
            "content region",
        ),
        (
            '        "content": content.get("message"),\n',
            '        "content": content.get("message"),\n        "ip_location": coarse_public_region((comment_item.get("reply_control") or {}).get("location") or comment_item.get("ip_location")),\n',
            "comment region",
        ),
    ])


def _patch_tieba_model(root: Path) -> bool:
    p = root / "model" / "m_baidu_tieba.py"
    text = _read(p)
    if MARKER in text:
        return False
    needle = '    publish_time: str = Field(default="", description="Publish time")\n'
    if text.count(needle) < 2:
        raise RuntimeError(f"Patch anchor not found twice for {p}:publish_time")
    replacement = needle + '    ip_location: str = Field(default="", description="Coarse public IP-location label")  # ' + MARKER + '\n'
    text = text.replace(needle, replacement, 2)
    _write(p, text)
    return True


def _patch_tieba_helper(root: Path) -> bool:
    p = root / "media_platform" / "tieba" / "help.py"
    text = _read(p)
    if MARKER in text:
        return False
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
        f"{p}:import",
    )
    text = _replace_once(
        text,
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n            tieba_name=tieba_name,\n',
        '            user_nickname=mask_nickname(author.get("name_show") or author.get("name") or ""),\n            ip_location=coarse_public_region(author.get("ip_address")),\n            tieba_name=tieba_name,\n',
        f"{p}:api note region",
    )
    text = _replace_once(
        text,
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n                tieba_id=tieba_id,\n',
        '                user_nickname=mask_nickname(user.get("name_show") or user.get("name") or ""),\n                ip_location=coarse_public_region(user.get("ip_address")),\n                tieba_id=tieba_id,\n',
        f"{p}:api comment region",
    )
    text = _replace_once(
        text,
        '            publish_time=publish_time,\n            total_replay_num=(\n',
        '            publish_time=publish_time,\n            ip_location=coarse_public_region(ip_location),\n            total_replay_num=(\n',
        f"{p}:html note region",
    )
    text = _replace_once(
        text,
        '                publish_time=publish_time,\n                note_id=note_id,\n',
        '                publish_time=publish_time,\n                ip_location=coarse_public_region(ip_location),\n                note_id=note_id,\n',
        f"{p}:html comment region",
    )
    _write(p, text)
    return True


def _patch_zhihu_model(root: Path) -> bool:
    p = root / "model" / "m_zhihu.py"
    text = _read(p)
    if MARKER in text:
        return False
    content_block = (
        '    source_keyword: str = Field(default="", description="Source keyword")\n'
        '    creator_hash: str = Field(default="", description="Creator anonymized hash")\n'
        '    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    )
    content_new = content_block + '    ip_location: str = Field(default="", description="Coarse public IP-location label")  # ' + MARKER + '\n'
    text = _replace_once(text, content_block, content_new, f"{p}:content field")
    comment_block = (
        '    content_type: str = Field(default="", description="Content type (article | answer | zvideo)")\n'
        '    creator_hash: str = Field(default="", description="Creator anonymized hash")\n'
        '    user_nickname: str = Field(default="", description="User nickname (masked)")\n'
    )
    comment_new = comment_block + '    ip_location: str = Field(default="", description="Coarse public IP-location label")\n'
    text = _replace_once(text, comment_block, comment_new, f"{p}:comment field")
    _write(p, text)
    return True


def _patch_zhihu_helper(root: Path) -> bool:
    p = root / "media_platform" / "zhihu" / "help.py"
    text = _read(p)
    if MARKER in text:
        return False
    text = _replace_once(
        text,
        "from tools.user_hash import anonymize_user_id, mask_nickname\n",
        "from tools.user_hash import anonymize_user_id, mask_nickname\nfrom tools.public_region import coarse_public_region  # " + MARKER + "\n",
        f"{p}:import",
    )
    # Content location is not consistently present, but keep it when the public payload exposes it.
    for typename in ("answer", "article", "zvideo"):
        anchor = f"        res.user_nickname = author_info.user_nickname\n        return res\n"
        replacement = (
            "        res.user_nickname = author_info.user_nickname\n"
            f"        res.ip_location = coarse_public_region({typename}.get(\"ip_location\") or ({typename}.get(\"author\") or {{}}).get(\"ip_location\"))\n"
            "        return res\n"
        )
        text = _replace_once(text, anchor, replacement, f"{p}:{typename} content region")
    text = _replace_once(
        text,
        "        res.user_nickname = author_info.user_nickname\n        return res\n\n    @staticmethod\n    def _extract_comment_ip_location",
        "        res.user_nickname = author_info.user_nickname\n        res.ip_location = coarse_public_region(self._extract_comment_ip_location(comment.get(\"comment_tag\") or comment.get(\"comment_tags\") or []))\n        return res\n\n    @staticmethod\n    def _extract_comment_ip_location",
        f"{p}:comment region",
    )
    _write(p, text)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch local MediaCrawler to retain only coarse public IP-location labels for aggregate monitoring.")
    ap.add_argument("--root", required=True, help="Local MediaCrawler root containing main.py")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not (root / "main.py").exists():
        raise SystemExit(f"MediaCrawler main.py not found under: {root}")

    helper = root / "tools" / "public_region.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(PUBLIC_REGION_HELPER, encoding="utf-8")

    patchers = [
        ("douyin", _patch_douyin),
        ("xhs", _patch_xhs),
        ("weibo", _patch_weibo),
        ("kuaishou", _patch_kuaishou),
        ("bilibili", _patch_bilibili),
        ("tieba_model", _patch_tieba_model),
        ("tieba_helper", _patch_tieba_helper),
        ("zhihu_model", _patch_zhihu_model),
        ("zhihu_helper", _patch_zhihu_helper),
    ]

    results: dict[str, str] = {}
    try:
        for name, fn in patchers:
            changed = fn(root)
            results[name] = "patched" if changed else "already_patched"
    except Exception as exc:
        results["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps({"ok": False, "version": PATCH_VERSION, "root": str(root), "results": results}, ensure_ascii=False, indent=2))
        return 2

    compile_targets = [
        helper,
        root / "store" / "douyin" / "__init__.py",
        root / "store" / "xhs" / "__init__.py",
        root / "store" / "weibo" / "__init__.py",
        root / "store" / "kuaishou" / "__init__.py",
        root / "store" / "bilibili" / "__init__.py",
        root / "model" / "m_baidu_tieba.py",
        root / "media_platform" / "tieba" / "help.py",
        root / "model" / "m_zhihu.py",
        root / "media_platform" / "zhihu" / "help.py",
    ]
    compile_ok = all(compileall.compile_file(str(p), quiet=1, force=True) for p in compile_targets)
    if not compile_ok:
        print(json.dumps({"ok": False, "version": PATCH_VERSION, "root": str(root), "results": results, "error": "Python compile check failed"}, ensure_ascii=False, indent=2))
        return 3

    manifest = {
        "version": PATCH_VERSION,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "privacy": "coarse_public_region_only_no_real_ip_no_precise_location",
        "files": [str(p.relative_to(root)) for p in compile_targets],
        "results": results,
    }
    (root / ".promotion_week_public_region_patch.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
