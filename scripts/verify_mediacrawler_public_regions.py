from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V2"
MARKER = PATCH_VERSION
PINNED_MEDIACRAWLER_COMMIT = "60e66f2a925816960bbd44af5d6c9b8385d79335"

REQUIRED_MARKER_FILES = (
    "store/douyin/__init__.py",
    "store/xhs/__init__.py",
    "store/weibo/__init__.py",
    "store/kuaishou/__init__.py",
    "store/bilibili/__init__.py",
    "model/m_baidu_tieba.py",
    "media_platform/tieba/help.py",
    "store/tieba/__init__.py",
    "model/m_zhihu.py",
    "media_platform/zhihu/help.py",
    "store/zhihu/__init__.py",
)


def _git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            text=True, capture_output=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the local MediaCrawler coarse public-region patch.")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()

    checks: list[dict] = []
    manifest_path = root / ".promotion_week_public_region_patch.json"
    helper_path = root / "tools" / "public_region.py"

    head = _git_head(root)
    checks.append({
        "name": "pinned_mediacrawler_commit",
        "ok": head == PINNED_MEDIACRAWLER_COMMIT,
        "detail": head or "unknown",
    })

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checks.append({
                "name": "manifest",
                "ok": manifest.get("version") == PATCH_VERSION,
                "detail": manifest.get("version"),
            })
        except Exception as exc:
            checks.append({"name": "manifest", "ok": False, "detail": f"invalid: {exc}"})
    else:
        checks.append({"name": "manifest", "ok": False, "detail": "missing"})

    helper_text = helper_path.read_text(encoding="utf-8", errors="replace") if helper_path.exists() else ""
    checks.append({
        "name": "public_region_helper",
        "ok": helper_path.exists() and "def coarse_public_region" in helper_text,
        "detail": str(helper_path),
    })

    for rel in REQUIRED_MARKER_FILES:
        path = root / rel
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        checks.append({
            "name": rel,
            "ok": bool(path.exists() and MARKER in text),
            "detail": "marker present" if MARKER in text else "marker missing",
        })

    semantic = {
        "dy_content_ip_label": (root / "store/douyin/__init__.py", 'save_content_item["ip_location"] = coarse_public_region(aweme_item.get("ip_label"))'),
        "dy_comment_ip_label": (root / "store/douyin/__init__.py", 'save_comment_item["ip_location"] = coarse_public_region(comment_item.get("ip_label"))'),
        "xhs_content_region": (root / "store/xhs/__init__.py", 'local_db_item["ip_location"] = coarse_public_region(note_item.get("ip_location")'),
        "xhs_comment_region": (root / "store/xhs/__init__.py", 'local_db_item["ip_location"] = coarse_public_region(comment_item.get("ip_location")'),
        "wb_content_region": (root / "store/weibo/__init__.py", 'save_content_item["ip_location"] = coarse_public_region'),
        "wb_comment_region": (root / "store/weibo/__init__.py", 'save_comment_item["ip_location"] = coarse_public_region'),
        "ks_content_region": (root / "store/kuaishou/__init__.py", 'save_content_item["ip_location"] = coarse_public_region'),
        "ks_comment_region": (root / "store/kuaishou/__init__.py", 'save_comment_item["ip_location"] = coarse_public_region'),
        "bili_comment_region": (root / "store/bilibili/__init__.py", 'reply_control'),
        "tieba_region_field": (root / "model/m_baidu_tieba.py", "ip_location: str"),
        "tieba_html_region": (root / "media_platform/tieba/help.py", "ip_location=coarse_public_region(ip_location)"),
        "zhihu_region_field": (root / "model/m_zhihu.py", "ip_location: str"),
        "zhihu_comment_region": (root / "media_platform/zhihu/help.py", "_extract_comment_ip_location"),
    }
    for name, (path, needle) in semantic.items():
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        checks.append({"name": name, "ok": needle in text, "detail": needle})

    failed = [c for c in checks if not c["ok"]]
    out = {
        "ok": not failed,
        "version": PATCH_VERSION,
        "root": str(root),
        "privacy": "coarse_public_region_only_no_real_ip_no_precise_location",
        "pinned_commit": PINNED_MEDIACRAWLER_COMMIT,
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
