from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

TARGET = Path(r"E:\MediaCrawler_clean\media_platform\kuaishou\client.py")
MARKER = "KUAISHOU_DIRECT_HTTPX_PATCH_V1"


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("Kuaishou direct-httpx patch is already installed.")
        print(f"Target: {TARGET}")
        return

    original = text

    # Kuaishou calls are timing out inside httpcore._async.http_proxy, which means
    # httpx is inheriting HTTP(S)_PROXY / ALL_PROXY from the environment even when
    # MediaCrawler itself has no explicit proxy configured.  Kuaishou is reachable
    # directly in the browser, so keep explicit MediaCrawler proxies working while
    # ignoring environment proxy variables for the Kuaishou API client.
    text = text.replace(
        "        timeout=10,\n",
        "        timeout=30,  # KUAISHOU_DIRECT_HTTPX_PATCH_V1: allow slower direct requests\n",
        1,
    )

    needle = "make_async_client(proxy=self.proxy)"
    replacement = "make_async_client(proxy=self.proxy, trust_env=False)"
    count = text.count(needle)
    if count == 0:
        raise SystemExit(
            "Patch anchor not found: make_async_client(proxy=self.proxy). "
            "No changes were made."
        )
    text = text.replace(needle, replacement)

    if text == original:
        raise SystemExit("No changes were made.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_direct_httpx_{stamp}")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(text, encoding="utf-8")

    print("Kuaishou direct-httpx patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print(f"Updated {count} Kuaishou httpx client construction site(s).")
    print("Behavior: Kuaishou API requests ignore environment proxy variables; an explicit MediaCrawler proxy, if configured, is still honored.")
    print("Request timeout default increased from 10s to 30s.")


if __name__ == "__main__":
    main()
