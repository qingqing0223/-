from __future__ import annotations

import argparse
import json
from pathlib import Path

PATCH_VERSION = "PROMOTION_WEEK_PUBLIC_REGION_PATCH_V1"
MARKER = PATCH_VERSION

REQUIRED_MARKER_FILES = (
    "store/douyin/__init__.py",
    "store/xhs/__init__.py",
    "store/weibo/__init__.py",
    "store/kuaishou/__init__.py",
    "store/bilibili/__init__.py",
    "model/m_baidu_tieba.py",
    "media_platform/tieba/help.py",
    "model/m_zhihu.py",
    "media_platform/zhihu/help.py",
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the local MediaCrawler coarse public-region patch.")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()

    checks: list[dict] = []
    manifest_path = root / ".promotion_week_public_region_patch.json"
    helper_path = root / "tools" / "public_region.py"

    manifest = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checks.append({"name": "manifest", "ok": manifest.get("version") == PATCH_VERSION, "detail": manifest.get("version")})
        except Exception as exc:
            checks.append({"name": "manifest", "ok": False, "detail": f"invalid: {exc}"})
    else:
        checks.append({"name": "manifest", "ok": False, "detail": "missing"})

    checks.append({"name": "public_region_helper", "ok": helper_path.exists(), "detail": str(helper_path)})

    for rel in REQUIRED_MARKER_FILES:
        path = root / rel
        ok = False
        detail = "missing"
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            ok = MARKER in text or (rel == "model/m_zhihu.py" and "Coarse public IP-location label" in text)
            detail = "marker present" if ok else "marker missing"
        checks.append({"name": rel, "ok": ok, "detail": detail})

    # Static semantic checks for the fields our pipeline needs.
    semantic = {
        "dy_content_ip_label": (root / "store/douyin/__init__.py", 'ip_location": coarse_public_region(aweme_item.get("ip_label"))'),
        "dy_comment_ip_label": (root / "store/douyin/__init__.py", 'ip_location": coarse_public_region(comment_item.get("ip_label"))'),
        "xhs_region": (root / "store/xhs/__init__.py", '"ip_location": coarse_public_region'),
        "wb_region": (root / "store/weibo/__init__.py", '"ip_location": coarse_public_region'),
        "tieba_region_field": (root / "model/m_baidu_tieba.py", "ip_location: str"),
        "zhihu_comment_region": (root / "media_platform/zhihu/help.py", "_extract_comment_ip_location"),
        "bili_comment_region": (root / "store/bilibili/__init__.py", "reply_control"),
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
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
