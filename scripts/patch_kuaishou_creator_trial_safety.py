from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


MARKER = "PROMOTION_WEEK_KS_CREATOR_TRIAL_SAFETY_V3"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def _method_bounds(text: str, class_name: str, method_name: str) -> tuple[int, int, str]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    start = offsets[child.lineno - 1]
                    end = offsets[child.end_lineno]
                    indent = lines[child.lineno - 1][: len(lines[child.lineno - 1]) - len(lines[child.lineno - 1].lstrip())]
                    return start, end, indent
    raise RuntimeError(f"{class_name}.{method_name} not found")


def _client_method(indent: str) -> str:
    i1, i2, i3, i4 = indent, indent + "    ", indent + "        ", indent + "            "
    return (
        f"{i1}async def get_all_videos_by_creator(\n"
        f"{i2}self,\n"
        f"{i2}user_id: str,\n"
        f"{i2}crawl_interval: float = 1.0,\n"
        f"{i2}callback: Optional[Callable] = None,\n"
        f"{i2}max_notes_count: int = 0,\n"
        f"{i1}) -> List[Dict]:\n"
        f"{i2}\"\"\"Fetch creator posts with an optional strict upper bound.\n\n"
        f"{i2}A non-positive limit preserves the historical fetch-until-no_more mode.\n"
        f"{i2}\"\"\"\n"
        f"{i2}# {MARKER}\n"
        f"{i2}result = []\n"
        f"{i2}pcursor = \"\"\n"
        f"{i2}limit = max(0, int(max_notes_count or 0))\n\n"
        f"{i2}while pcursor != \"no_more\":\n"
        f"{i3}if limit and len(result) >= limit:\n"
        f"{i4}break\n"
        f"{i3}videos_res = await self.get_video_by_creater_v2(user_id, pcursor)\n"
        f"{i3}if not videos_res:\n"
        f"{i4}utils.logger.error(\n"
        f"{i4}    f\"[KuaiShouClient.get_all_videos_by_creator] creator feed unavailable for user_id: {{user_id}}\"\n"
        f"{i4})\n"
        f"{i4}break\n"
        f"{i3}result_code = videos_res.get(\"result\")\n"
        f"{i3}if result_code != 1:\n"
        f"{i4}utils.logger.error(\n"
        f"{i4}    f\"[KuaiShouClient.get_all_videos_by_creator] ks api returned business error \"\n"
        f"{i4}    f\"(result: {{result_code}}), stop pagination for user_id: {{user_id}}\"\n"
        f"{i4})\n"
        f"{i4}break\n"
        f"{i3}pcursor = videos_res.get(\"pcursor\", \"\")\n"
        f"{i3}videos = list(videos_res.get(\"feeds\", []) or [])\n"
        f"{i3}if limit:\n"
        f"{i4}videos = videos[: max(0, limit - len(result))]\n"
        f"{i3}utils.logger.info(\n"
        f"{i4}f\"[KuaiShouClient.get_all_videos_by_creator] got user_id:{{user_id}} videos len : {{len(videos)}}\"\n"
        f"{i3})\n"
        f"{i3}if not videos:\n"
        f"{i4}break\n"
        f"{i3}if callback:\n"
        f"{i4}await callback(videos)\n"
        f"{i3}result.extend(videos)\n"
        f"{i3}if limit and len(result) >= limit:\n"
        f"{i4}utils.logger.info(\n"
        f"{i4}    f\"[KuaiShouClient.get_all_videos_by_creator] hard limit reached: {{limit}}\"\n"
        f"{i4})\n"
        f"{i4}break\n"
        f"{i3}if pcursor == \"no_more\":\n"
        f"{i4}break\n"
        f"{i3}await asyncio.sleep(crawl_interval + random.uniform(1, 3))\n"
        f"{i2}return result\n"
    )


def _core_method(indent: str) -> str:
    i1, i2, i3, i4 = indent, indent + "    ", indent + "        ", indent + "            "
    return (
        f"{i1}async def get_creators_and_videos(self) -> None:\n"
        f"{i2}\"\"\"Validate each creator profile before bounded post pagination.\"\"\"\n"
        f"{i2}# {MARKER}\n"
        f"{i2}utils.logger.info(\"[KuaiShouCrawler.get_creators_and_videos] Begin get kuaishou creators\")\n"
        f"{i2}for creator_url in config.KS_CREATOR_ID_LIST:\n"
        f"{i3}try:\n"
        f"{i4}creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)\n"
        f"{i4}requested_user_id = creator_info.user_id\n"
        f"{i4}profile: Dict = await self.ks_client.get_creator_info(user_id=requested_user_id)\n"
        f"{i3}except Exception as exc:\n"
        f"{i4}utils.logger.error(\n"
        f"{i4}    \"[KS_CREATOR_PROFILE_INVALID] \" + json.dumps({{\n"
        f"{i4}        \"profile_valid\": False, \"requested_creator_id\": str(creator_url),\n"
        f"{i4}        \"reason\": f\"{{type(exc).__name__}}: {{exc}}\",\n"
        f"{i4}    }}, ensure_ascii=False)\n"
        f"{i4})\n"
        f"{i4}continue\n"
        f"{i3}if not isinstance(profile, dict) or not profile:\n"
        f"{i4}utils.logger.error(\n"
        f"{i4}    \"[KS_CREATOR_PROFILE_INVALID] \" + json.dumps({{\n"
        f"{i4}        \"profile_valid\": False, \"requested_creator_id\": requested_user_id,\n"
        f"{i4}        \"reason\": \"empty_userProfile\",\n"
        f"{i4}    }}, ensure_ascii=False)\n"
        f"{i4})\n"
        f"{i4}continue\n"
        f"{i3}returned_user_id = str(profile.get(\"user_id\") or profile.get(\"userId\") or profile.get(\"id\") or \"\").strip()\n"
        f"{i3}pagination_user_id = returned_user_id or requested_user_id\n"
        f"{i3}nickname = profile.get(\"name\") or profile.get(\"user_name\") or profile.get(\"userName\") or profile.get(\"nickname\")\n"
        f"{i3}profile_url = f\"https://www.kuaishou.com/profile/{{pagination_user_id}}\"\n"
        f"{i3}utils.logger.info(\n"
        f"{i4}\"[KS_CREATOR_PROFILE_VALID] \" + json.dumps({{\n"
        f"{i4}    \"profile_valid\": True, \"requested_creator_id\": requested_user_id,\n"
        f"{i4}    \"stable_account_id\": returned_user_id or None, \"nickname\": nickname,\n"
        f"{i4}    \"profile_url\": profile_url,\n"
        f"{i4}}}, ensure_ascii=False)\n"
        f"{i3})\n"
        f"{i3}await kuaishou_store.save_creator(pagination_user_id, creator=profile)\n"
        f"{i3}all_video_list = await self.ks_client.get_all_videos_by_creator(\n"
        f"{i4}user_id=pagination_user_id, crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,\n"
        f"{i4}callback=self.fetch_creator_video_detail,\n"
        f"{i4}max_notes_count=config.CRAWLER_MAX_NOTES_COUNT,\n"
        f"{i3})\n"
        f"{i3}utils.logger.info(\n"
        f"{i4}f\"[KuaishouCrawler.get_creators_and_videos] creator: {{pagination_user_id}}, got {{len(all_video_list)}} videos\"\n"
        f"{i3})\n"
        f"{i3}video_ids = [item.get(\"photo\", {{}}).get(\"id\") for item in all_video_list]\n"
        f"{i3}video_ids = [video_id for video_id in video_ids if video_id]\n"
        f"{i3}await self.batch_get_video_comments(video_ids)\n"
    )


def patch(root: Path) -> None:
    client = root / "media_platform/kuaishou/client.py"
    core = root / "media_platform/kuaishou/core.py"
    client_text = _read(client)
    legacy_profile = (
        "        visionProfile = await self.get_creator_profile(user_id)\n"
        "        return visionProfile.get(\"userProfile\")\n"
    )
    fixed_profile = (
        "        profile_response = await self.get_creator_profile(user_id)\n"
        "        vision_profile = profile_response.get(\"visionProfile\", {}) if isinstance(profile_response, dict) else {}\n"
        "        return vision_profile.get(\"userProfile\") if isinstance(vision_profile, dict) else None\n"
    )
    if legacy_profile in client_text:
        client_text = client_text.replace(legacy_profile, fixed_profile, 1)
    if MARKER not in client_text:
        start, end, indent = _method_bounds(client_text, "KuaiShouClient", "get_all_videos_by_creator")
        _write(client, client_text[:start] + _client_method(indent) + client_text[end:])
    core_text = _read(core)
    if "import json\n" not in core_text:
        core_text = core_text.replace("import asyncio\n", "import asyncio\nimport json\n", 1)
    if MARKER not in core_text:
        start, end, indent = _method_bounds(core_text, "KuaishouCrawler", "get_creators_and_videos")
        core_text = core_text[:start] + _core_method(indent) + core_text[end:]
    _write(core, core_text)


def check(root: Path) -> dict:
    client_text = _read(root / "media_platform/kuaishou/client.py")
    core_text = _read(root / "media_platform/kuaishou/core.py")
    result = {
        "client_marker": MARKER in client_text,
        "core_marker": MARKER in core_text,
        "strict_slice": "videos[: max(0, limit - len(result))]" in client_text,
        "unlimited_mode": "limit = max(0, int(max_notes_count or 0))" in client_text,
        "profile_gate": "[KS_CREATOR_PROFILE_INVALID]" in core_text and "if not isinstance(profile, dict) or not profile" in core_text,
        "profile_audit": "[KS_CREATOR_PROFILE_VALID]" in core_text,
        "limit_wired": "max_notes_count=config.CRAWLER_MAX_NOTES_COUNT" in core_text,
        "profile_response_unwrapped": "profile_response.get(\"visionProfile\", {})" in client_text,
    }
    result["ok"] = all(result.values())
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not args.check:
        patch(root)
    result = {"root": str(root), **check(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
