from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def main():
    ingest_url = os.environ.get("SUQI_INGEST_URL", "http://127.0.0.1:8765/api/ingest").strip()
    health_url = ingest_url.rsplit("/api/ingest", 1)[0] + "/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(json.dumps({"ok": True, "url": health_url, "response": body}, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "url": health_url,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "If Suqi's server is on another computer, set SUQI_INGEST_URL to that computer's reachable LAN/server URL."
        }, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
