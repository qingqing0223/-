from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_BILI_NETWORK_RESILIENCE_V1"


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


def patch_client(root: Path) -> None:
    path = root / "media_platform/bilibili/client.py"
    text = read(path)
    if f"# {MARKER}: bounded transport retry" in text:
        return

    old = '''        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        try:
            data: Dict = response.json()
'''
    new = f'''        # {MARKER}: bounded transport retry.
        # Bilibili occasionally closes an HTTP/1.1 chunked response early
        # (httpx.RemoteProtocolError / incomplete chunked read). One transient
        # transport failure must not abort the whole realtime cycle.
        response = None
        _bili_transport_exc = None
        for _bili_request_attempt in range(2):
            try:
                async with make_async_client(proxy=self.proxy) as client:
                    response = await client.request(method, url, timeout=self.timeout, **kwargs)
                break
            except httpx.TransportError as _bili_exc:
                _bili_transport_exc = _bili_exc
                utils.logger.warning(
                    f"[BILIBILI_HTTP_RETRY] attempt={{_bili_request_attempt + 1}} "
                    f"type={{type(_bili_exc).__name__}} url={{url}}"
                )
                if _bili_request_attempt < 1:
                    await asyncio.sleep(1)

        if response is None:
            raise _bili_transport_exc

        try:
            data: Dict = response.json()
'''
    text = replace_once(text, old, new, "Bilibili client bounded transport retry")
    write_py(path, text)


def patch_core(root: Path) -> None:
    path = root / "media_platform/bilibili/core.py"
    text = read(path)

    if "import httpx\n" not in text:
        anchor = "import pandas as pd\n"
        if anchor not in text:
            raise RuntimeError("Bilibili core httpx import anchor missing")
        text = text.replace(anchor, anchor + "import httpx\n", 1)

    if f"# {MARKER}: isolate per-video transport failures" not in text:
        old = '''            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] Get video detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] have not fund note detail video_id:{bvid}, err: {ex}")
                return None
'''
        new = f'''            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] Get video detail error: {{ex}}")
                return None
            # {MARKER}: isolate per-video transport failures.
            # The client already retries once. If the peer still closes the
            # response early, skip only this video instead of aborting
            # asyncio.gather() and losing every other valid search result.
            except httpx.TransportError as ex:
                utils.logger.warning(
                    f"[BILIBILI_VIDEO_DETAIL_TRANSPORT_SKIP] "
                    f"video_id={{bvid or aid}} type={{type(ex).__name__}} detail={{str(ex)[:200]}}"
                )
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] have not fund note detail video_id:{{bvid}}, err: {{ex}}")
                return None
'''
        text = replace_once(text, old, new, "Bilibili per-video transport isolation")

    if f"# {MARKER}: isolate comment transport failures" not in text:
        old = '''            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_comments] get video_id: {video_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_comments] may be been blocked, err:{e}")
                # Propagate the exception to be caught by the main loop
                raise
'''
        new = f'''            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_comments] get video_id: {{video_id}} comment error: {{ex}}")
            # {MARKER}: isolate comment transport failures.
            # Do not let one incomplete/closed HTTP response cancel comments
            # for every other video in the batch.
            except httpx.TransportError as ex:
                utils.logger.warning(
                    f"[BILIBILI_COMMENT_TRANSPORT_SKIP] "
                    f"video_id={{video_id}} type={{type(ex).__name__}} detail={{str(ex)[:200]}}"
                )
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_comments] may be been blocked, err:{{e}}")
                # Preserve upstream behavior for non-transport programming or
                # platform errors so they remain visible during diagnostics.
                raise
'''
        text = replace_once(text, old, new, "Bilibili comment transport isolation")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/bilibili/client.py"
    core = root / "media_platform/bilibili/core.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "core_exists": core.exists(),
        "client_transport_retry": False,
        "video_detail_transport_isolation": False,
        "comment_transport_isolation": False,
        "httpx_import": False,
        "ok": False,
    }
    if not client.exists() or not core.exists():
        return result

    try:
        client_text = read(client)
        core_text = read(core)
        ast.parse(client_text, filename=str(client))
        ast.parse(core_text, filename=str(core))
        result["client_transport_retry"] = (
            f"# {MARKER}: bounded transport retry" in client_text
            and "for _bili_request_attempt in range(2):" in client_text
            and "[BILIBILI_HTTP_RETRY]" in client_text
        )
        result["video_detail_transport_isolation"] = (
            f"# {MARKER}: isolate per-video transport failures" in core_text
            and "BILIBILI_VIDEO_DETAIL_TRANSPORT_SKIP" in core_text
        )
        result["comment_transport_isolation"] = (
            f"# {MARKER}: isolate comment transport failures" in core_text
            and "BILIBILI_COMMENT_TRANSPORT_SKIP" in core_text
        )
        result["httpx_import"] = "import httpx\n" in core_text
        result["ok"] = all([
            result["client_transport_retry"],
            result["video_detail_transport_isolation"],
            result["comment_transport_isolation"],
            result["httpx_import"],
        ])
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch Bilibili API transport resilience so incomplete chunked responses do not abort realtime cycles."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        if not args.check:
            patch_client(root)
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
        "purpose": "bilibili_http_transport_retry_and_per_item_failure_isolation",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
