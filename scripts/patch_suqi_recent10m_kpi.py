from __future__ import annotations

from pathlib import Path
import shutil
from datetime import datetime

TARGET = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system\stats.py")
MARKER = "# [qingqing integration] realtime top KPI"
INSERT_BEFORE = "    # 原话池（历史 + 实时）\n"

BLOCK = r'''    # [qingqing integration] realtime top KPI
    # These fields are consumed by the realtime dashboard contract.
    # recent10mInfo is based on collected_at / first-seen time, not publish time.
    cutoff = datetime.now() - timedelta(minutes=10)
    recent10m = 0
    for _r in live["rows"]:
        _raw = (_r["collected_at"] or "").strip()
        if not _raw:
            continue
        try:
            _dt = datetime.fromisoformat(_raw.replace("Z", "+00:00"))
            if _dt.tzinfo is not None:
                _dt = _dt.astimezone().replace(tzinfo=None)
            if _dt >= cutoff:
                recent10m += 1
        except Exception:
            pass

    ts["cumulativeInfo"] = ts.get("totalOpinions", 0) or 0
    ts["recent10mInfo"] = recent10m
    ts["detectedRegionCount"] = sum(
        1 for _x in base.get("provinces", [])
        if (_x.get("total", 0) or _x.get("value", 0) or 0) > 0
    )
    ts["detectedPlatformCount"] = sum(
        1 for _x in base.get("platforms", [])
        if (_x.get("total", 0) or 0) > 0
    )

'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("Patch already applied.")
        return
    if INSERT_BEFORE not in text:
        raise SystemExit("Expected insertion marker not found; Suqi stats.py may have changed. No file was modified.")

    backup = TARGET.with_name(TARGET.name + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(TARGET, backup)
    text = text.replace(INSERT_BEFORE, BLOCK + INSERT_BEFORE, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("Patched:", TARGET)
    print("Backup:", backup)
    print("Restart Suqi server.py after applying this patch.")


if __name__ == "__main__":
    main()
