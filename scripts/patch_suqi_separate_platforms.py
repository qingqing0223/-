from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

TARGET = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system\stats.py")
OLD = '        g = r["platform_group"] or "其他"'
NEW = '        g = r["platform"] or r["platform_group"] or "其他"'


def main():
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8", errors="replace")
    if NEW in text:
        print("Suqi separate-platform live statistics patch is already installed.")
        return
    if OLD not in text:
        raise SystemExit(
            "Could not locate the expected platform-group aggregation line in stats.py; no changes made. "
            "Ask the dashboard maintainer to update compute_live_stats() so platform statistics use r['platform'] first."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_separate_platforms_{stamp}")
    shutil.copy2(TARGET, backup)

    patched = text.replace(OLD, NEW, 1)
    TARGET.write_text(patched, encoding="utf-8")

    print("Suqi separate-platform live statistics patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print("Effect: live platform statistics now prefer exact platform names instead of grouped platform categories.")
    print("Restart server.py and hard-refresh the dashboard after applying this patch.")
    print("Note: this patch does not remove the old historical baseline; formal preheat data still needs a clean current-task baseline.")


if __name__ == "__main__":
    main()
