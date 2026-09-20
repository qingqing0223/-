from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V4"
MARKER = PATCH_VERSION
PINNED_MEDIACRAWLER_COMMIT = "60e66f2a925816960bbd44af5d6c9b8385d79335"

REQUIRED_MARKER_FILES = (
    "store/douyin/__init__.py",
    "store/xhs/__init__.py",
    "store/weibo/__init__.py",
    "store/kuaishou/__init__.py",
    "store/bilibili/__init__.py",
    "model/m_zhihu.py",
    "media_platform/zhihu/help.py",
    "store/zhihu/__init__.py",
)


def git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            text=True, capture_output=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def add(checks: list[dict], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify pinned MediaCrawler and its coarse public-region patch.")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    checks: list[dict] = []

    head = git_head(root)
    add(checks, "pinned_mediacrawler_commit", head == PINNED_MEDIACRAWLER_COMMIT, head or "unknown")

    manifest_path = root / ".promotion_week_public_region_patch.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            add(checks, "manifest", manifest.get("version") == PATCH_VERSION, str(manifest.get("version")))
        except Exception as exc:
            add(checks, "manifest", False, f"invalid: {exc}")
    else:
        add(checks, "manifest", False, "missing")

    helper = root / "tools/public_region.py"
    helper_ok = False
    helper_detail = "missing"
    if helper.exists():
        try:
            spec = importlib.util.spec_from_file_location("promotion_week_public_region", helper)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            cases = {
                "IP属地：山东": "山东",
                "来自: 北京": "北京",
                "发布于 上海": "上海",
                "所在地：内蒙古自治区": "内蒙古",
                "1.2.3.4": "",
                "2001:db8::1": "",
                "未知": "",
                "CN": "",
                "China": "",
            }
            got = {k: module.coarse_public_region(k) for k in cases}
            helper_ok = got == cases
            helper_detail = json.dumps(got, ensure_ascii=False)
        except Exception as exc:
            helper_detail = f"{type(exc).__name__}: {exc}"
    add(checks, "public_region_helper_runtime", helper_ok, helper_detail)

    for rel in REQUIRED_MARKER_FILES:
        path = root / rel
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        add(checks, rel, path.exists() and MARKER in text, "marker present" if MARKER in text else "marker missing")

    semantic = {
        "dy_content_region": (root / "store/douyin/__init__.py", 'save_content_item["ip_location"] = first_coarse_public_region('),
        "dy_comment_region": (root / "store/douyin/__init__.py", 'save_comment_item["ip_location"] = first_coarse_public_region('),
        "dy_comment_user_fallback": (root / "store/douyin/__init__.py", 'user_info.get("ip_region")'),
        "dy_first_valid_region_helper": (root / "store/douyin/__init__.py", "first_coarse_public_region"),
        "xhs_content_region": (root / "store/xhs/__init__.py", 'local_db_item["ip_location"] = coarse_public_region('),
        "xhs_content_region_variants": (root / "store/xhs/__init__.py", 'note_item.get("ipLocation")'),
        "xhs_comment_user_fallback": (root / "store/xhs/__init__.py", 'user_info.get("ipRegion")'),
        "wb_content_region": (root / "store/weibo/__init__.py", 'save_content_item["ip_location"] = coarse_public_region('),
        "wb_comment_region": (root / "store/weibo/__init__.py", 'save_comment_item["ip_location"] = coarse_public_region('),
        "ks_content_region": (root / "store/kuaishou/__init__.py", 'save_content_item["ip_location"] = coarse_public_region('),
        "ks_comment_nested_user": (root / "store/kuaishou/__init__.py", '(comment_item.get("user") or {}).get("ip_region")'),
        "bili_comment_region": (root / "store/bilibili/__init__.py", 'reply_control'),
        "bili_member_region_fallback": (root / "store/bilibili/__init__.py", '(comment_item.get("member") or {}).get("ip_region")'),
        "zhihu_region_field": (root / "model/m_zhihu.py", "ip_location: str"),
        "zhihu_comment_region": (root / "media_platform/zhihu/help.py", "_extract_comment_ip_location"),
    }
    for name, (path, needle) in semantic.items():
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        add(checks, name, needle in text, needle)

    failed = [c for c in checks if not c["ok"]]
    result = {
        "ok": not failed,
        "version": PATCH_VERSION,
        "root": str(root),
        "privacy": "coarse_public_region_only_no_real_ip_no_precise_location",
        "pinned_commit": PINNED_MEDIACRAWLER_COMMIT,
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
