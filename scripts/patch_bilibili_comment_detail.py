from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_DETAIL_AID_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_core(root: Path) -> None:
    path = root / "media_platform/bilibili/core.py"
    text = read(path)
    if f"# {MARKER}: accept AV/AID detail identifiers" in text:
        return

    old = '''        utils.logger.info("[BilibiliCrawler.get_specified_videos] Parsing video URLs...")
        bvids_list = []
        for video_url in video_url_list:
            try:
                video_info = parse_video_info_from_url(video_url)
                bvids_list.append(video_info.video_id)
                utils.logger.info(f"[BilibiliCrawler.get_specified_videos] Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_specified_videos] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_video_info_task(aid=0, bvid=video_id, semaphore=semaphore) for video_id in bvids_list]
        video_details = await asyncio.gather(*task_list)
'''
    new = f'''        utils.logger.info("[BilibiliCrawler.get_specified_videos] Parsing video URLs...")
        # {MARKER}: accept AV/AID detail identifiers.
        # Search JSONL stores Bilibili's numeric aid and an /video/av<aid> URL.
        # Upstream detail parsing accepted only BV identifiers, so realtime
        # comment recovery selected valid candidates but then produced
        # video ids:[] and no comment JSONL. Preserve BV support while routing
        # numeric/AV candidates through get_video_info(aid=...).
        aids_list = []
        bvids_list = []
        for video_url in video_url_list:
            raw_video = str(video_url or "").strip()
            try:
                raw_lower = raw_video.lower()
                aid_value = ""
                if raw_video.isdigit():
                    aid_value = raw_video
                elif "/video/av" in raw_lower:
                    tail = raw_lower.split("/video/av", 1)[1]
                    aid_value = "".join(ch for ch in tail if ch.isdigit())
                elif raw_lower.startswith("av") and raw_video[2:].isdigit():
                    aid_value = raw_video[2:]

                if aid_value:
                    aids_list.append(int(aid_value))
                    utils.logger.info(
                        f"[BILIBILI_DETAIL_ID] parsed aid={{aid_value}} from {{raw_video}}"
                    )
                    continue

                video_info = parse_video_info_from_url(raw_video)
                bvids_list.append(video_info.video_id)
                utils.logger.info(
                    f"[BILIBILI_DETAIL_ID] parsed bvid={{video_info.video_id}} from {{raw_video}}"
                )
            except ValueError as e:
                utils.logger.error(
                    f"[BilibiliCrawler.get_specified_videos] Failed to parse video URL: {{e}}"
                )
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_video_info_task(aid=aid, bvid="", semaphore=semaphore)
            for aid in aids_list
        ] + [
            self.get_video_info_task(aid=0, bvid=bvid, semaphore=semaphore)
            for bvid in bvids_list
        ]
        video_details = await asyncio.gather(*task_list)
'''
    text = replace_once(text, old, new, "Bilibili AV/AID detail parsing")
    write_py(path, text)


def check(root: Path) -> dict:
    core = root / "media_platform/bilibili/core.py"
    result = {
        "patch_version": 1,
        "core_exists": core.exists(),
        "aid_detail_support": False,
        "av_url_support": False,
        "bv_support_preserved": False,
        "aid_task_routing": False,
        "ok": False,
    }
    if not core.exists():
        return result
    try:
        text = read(core)
        ast.parse(text, filename=str(core))
        result["aid_detail_support"] = (
            f"# {MARKER}: accept AV/AID detail identifiers" in text
            and "if raw_video.isdigit():" in text
        )
        result["av_url_support"] = 'elif "/video/av" in raw_lower:' in text
        result["bv_support_preserved"] = "parse_video_info_from_url(raw_video)" in text
        result["aid_task_routing"] = "self.get_video_info_task(aid=aid, bvid=\"\", semaphore=semaphore)" in text
        result["ok"] = all([
            result["aid_detail_support"],
            result["av_url_support"],
            result["bv_support_preserved"],
            result["aid_task_routing"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch Bilibili detail mode so numeric AID/av URLs discovered by search can be used for comment recovery."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_core(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps({
        "root": str(root),
        **result,
        "purpose": "bilibili_realtime_comment_detail_accepts_search_aid_and_av_urls",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
