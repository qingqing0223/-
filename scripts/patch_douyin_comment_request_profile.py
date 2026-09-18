from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_DY_COMMENT_REQUEST_PROFILE_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def patch_client(root: Path) -> None:
    path = root / "media_platform/douyin/client.py"
    text = read(path)
    if MARKER in text:
        return

    old = """        params.update(common_params)
        query_string = urllib.parse.urlencode(params)
"""
    new = f"""        params.update(common_params)

        # {MARKER}: align public comment-list requests with the current
        # Windows web request profile used by Douyin's public comment endpoint.
        # This does not bypass login/captcha/security checks. It only supplies
        # ordinary browser/profile query parameters that the endpoint itself
        # exposes and prefers, so optional public response fields (notably
        # comment ip_label) are not silently reduced to user.region='CN'.
        if uri.startswith("/aweme/v1/web/comment/list/"):
            _dy_ms_token = (
                local_storage.get("xmst")
                or local_storage.get("msToken")
                or self.cookie_dict.get("msToken")
                or ""
            )
            _dy_verify_fp = (
                local_storage.get("s_v_web_id")
                or local_storage.get("verifyFp")
                or local_storage.get("verify_fp")
                or self.cookie_dict.get("s_v_web_id")
                or self.cookie_dict.get("verifyFp")
                or ""
            )
            params.update({{
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "pc_client_type": "1",
                "cookie_enabled": "true",
                "browser_language": "zh-CN",
                "browser_platform": "Win32",
                "browser_name": "Chrome",
                "browser_version": "125.0.0.0",
                "browser_online": "true",
                "engine_name": "Blink",
                "engine_version": "125.0.0.0",
                "os_name": "Windows",
                "os_version": "10",
                "cpu_core_num": "16",
                "device_memory": "8",
                "platform": "PC",
                "downlink": "10",
                "effective_type": "4g",
                "round_trip_time": "50",
                "version_code": "170400",
                "version_name": "17.4.0",
                "screen_width": "1552",
                "screen_height": "970",
            }})
            if _dy_ms_token:
                params["msToken"] = _dy_ms_token
            else:
                params.pop("msToken", None)
            if _dy_verify_fp:
                params["verifyFp"] = _dy_verify_fp
                params["fp"] = _dy_verify_fp

            if uri == "/aweme/v1/web/comment/list/":
                params.setdefault("insert_ids", "")
                params.setdefault("whale_cut_token", "")
                params.setdefault("cut_version", "1")
                params.setdefault("rcFT", "")
            elif uri == "/aweme/v1/web/comment/list/reply/":
                params.setdefault("cut_version", "1")
                params.setdefault("pc_libra_divert", "Windows")
                params.setdefault("support_h265", "1")
                params.setdefault("support_dash", "1")

        query_string = urllib.parse.urlencode(params)
"""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Douyin request-profile anchor expected once, found {count}")
    text = text.replace(old, new, 1)

    # Fetch a larger page from the same official public endpoint to reduce
    # pagination overhead inside the five-minute realtime cycle.
    text = text.replace(
        'params = {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0}',
        'params = {"aweme_id": aweme_id, "cursor": cursor, "count": 50, "item_type": 0}',
        1,
    )
    write_py(path, text)


def check(root: Path) -> dict:
    path = root / "media_platform/douyin/client.py"
    result = {
        "patch_version": 1,
        "client_exists": path.exists(),
        "marker_present": False,
        "windows_comment_profile": False,
        "comment_optional_params": False,
        "session_token_reuse": False,
        "comment_page_size_50": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        text = read(path)
        ast.parse(text, filename=str(path))
        result["marker_present"] = MARKER in text
        result["windows_comment_profile"] = all(
            needle in text
            for needle in (
                '"browser_platform": "Win32"',
                '"os_name": "Windows"',
                '"version_code": "170400"',
                '"version_name": "17.4.0"',
            )
        )
        result["comment_optional_params"] = all(
            needle in text
            for needle in (
                'params.setdefault("insert_ids", "")',
                'params.setdefault("whale_cut_token", "")',
                'params.setdefault("cut_version", "1")',
                'params.setdefault("rcFT", "")',
            )
        )
        result["session_token_reuse"] = all(
            needle in text for needle in ('self.cookie_dict.get("msToken")', 'params["verifyFp"]')
        )
        result["comment_page_size_50"] = '"count": 50' in text
        result["ok"] = all(
            result[key]
            for key in (
                "marker_present",
                "windows_comment_profile",
                "comment_optional_params",
                "session_token_reuse",
                "comment_page_size_50",
            )
        )
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch Douyin public comment request profile for stable public ip_label exposure."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_client(root)
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
        "purpose": "douyin_public_comment_request_profile_for_public_region_field",
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
