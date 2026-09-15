from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil

TARGET = Path(r"E:\Real-time-situation-map\yuqing-v1\03_live_system\db.py")

NEW_FUNC = r'''def insert_incident(rec):
    """Insert one incident or enrich an existing uid in place.

    This lets a later detail/comment pass fill public province/IP-location labels
    for an item that was already shown on the dashboard. Empty enrichment values
    never erase existing values. Interaction counters only move upward.
    """
    sql = """
    INSERT INTO incidents(
        uid, collected_at, published_at, platform, platform_group, source, account, text, url,
        region, province, city, ip_location, language, is_minority, attitude, attitude_bucket,
        issue_category, likes, comments, shares, is_key, is_relevant, status, notes, origin
    ) VALUES(
        :uid, :collected_at, :published_at, :platform, :platform_group, :source, :account, :text, :url,
        :region, :province, :city, :ip_location, :language, :is_minority, :attitude, :attitude_bucket,
        :issue_category, :likes, :comments, :shares, :is_key, :is_relevant, :status, :notes, :origin
    )
    ON CONFLICT(uid) DO UPDATE SET
        collected_at = CASE WHEN excluded.collected_at <> '' THEN excluded.collected_at ELSE incidents.collected_at END,
        published_at = CASE WHEN excluded.published_at <> '' THEN excluded.published_at ELSE incidents.published_at END,
        source = CASE WHEN excluded.source <> '' THEN excluded.source ELSE incidents.source END,
        account = CASE WHEN excluded.account <> '' THEN excluded.account ELSE incidents.account END,
        text = CASE WHEN excluded.text <> '' THEN excluded.text ELSE incidents.text END,
        url = CASE WHEN excluded.url <> '' THEN excluded.url ELSE incidents.url END,
        region = CASE WHEN excluded.region <> '' THEN excluded.region ELSE incidents.region END,
        province = CASE WHEN excluded.province <> '' THEN excluded.province ELSE incidents.province END,
        city = CASE WHEN excluded.city <> '' THEN excluded.city ELSE incidents.city END,
        ip_location = CASE WHEN excluded.ip_location <> '' THEN excluded.ip_location ELSE incidents.ip_location END,
        language = CASE WHEN excluded.language <> '' THEN excluded.language ELSE incidents.language END,
        attitude = CASE WHEN excluded.attitude <> '' THEN excluded.attitude ELSE incidents.attitude END,
        attitude_bucket = CASE WHEN excluded.attitude_bucket <> '' THEN excluded.attitude_bucket ELSE incidents.attitude_bucket END,
        issue_category = CASE WHEN excluded.issue_category <> '' THEN excluded.issue_category ELSE incidents.issue_category END,
        likes = MAX(incidents.likes, excluded.likes),
        comments = MAX(incidents.comments, excluded.comments),
        shares = MAX(incidents.shares, excluded.shares),
        is_key = MAX(incidents.is_key, excluded.is_key),
        is_relevant = excluded.is_relevant,
        status = excluded.status,
        notes = CASE WHEN excluded.notes <> '' THEN excluded.notes ELSE incidents.notes END,
        origin = CASE WHEN incidents.origin = 'history' THEN incidents.origin ELSE excluded.origin END
    """
    with _lock:
        conn = get_conn()
        try:
            conn.execute(sql, rec)
            conn.commit()
            row = conn.execute("SELECT * FROM incidents WHERE uid=?", (rec["uid"],)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
'''


def main():
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    if "ON CONFLICT(uid) DO UPDATE SET" in text and "late region" not in text:
        print("Suqi region upsert already appears to be installed.")
        return

    pattern = re.compile(r"def insert_incident\(rec\):\n.*?(?=\ndef log_collector_run\()", re.S)
    if not pattern.search(text):
        raise SystemExit("Could not locate insert_incident() block; no changes made.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_region_upsert_{stamp}")
    shutil.copy2(TARGET, backup)

    patched = pattern.sub(NEW_FUNC.rstrip() + "\n", text, count=1)
    TARGET.write_text(patched, encoding="utf-8")

    print("Suqi late-region upsert patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print("Restart server.py after applying this patch.")


if __name__ == "__main__":
    main()
