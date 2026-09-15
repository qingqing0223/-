from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

TARGET = Path(r"E:\MediaCrawler_clean\media_platform\kuaishou\core.py")
MARKER = "KS_HOMEPAGE_TIMEOUT_PATCH_V1"

OLD = '''            await self.context_page.goto(f"{self.index_url}?isHome=1")\n'''

NEW = '''            # KS_HOMEPAGE_TIMEOUT_PATCH_V1\n            # Kuaishou's homepage can keep background resources loading for a long time.\n            # For our test we only need the DOM/session to become usable; do not wait\n            # indefinitely for every resource to reach the full \"load\" state.\n            try:\n                await self.context_page.goto(\n                    f"{self.index_url}?isHome=1",\n                    wait_until="domcontentloaded",\n                    timeout=60000,\n                )\n            except Exception as ex:\n                utils.logger.warning(\n                    f"[KuaishouCrawler.start] Homepage navigation timed out or was interrupted: {ex}. "\n                    "Continuing with the current page so login/search can determine whether the session is usable."\n                )\n                await asyncio.sleep(2)\n'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("Kuaishou homepage timeout patch is already installed.")
        print(f"Target: {TARGET}")
        return

    if OLD not in text:
        raise SystemExit(
            "Patch anchor not found. MediaCrawler kuaishou/core.py differs from the expected version; "
            "no changes were made."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_homepage_timeout_{stamp}")
    shutil.copy2(TARGET, backup)

    patched = text.replace(OLD, NEW, 1)
    TARGET.write_text(patched, encoding="utf-8")

    print("Kuaishou homepage timeout patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print("Behavior: homepage navigation waits for DOMContentLoaded for up to 60s instead of full page load; if it still times out, the run continues so the next login/search step can report the real state.")


if __name__ == "__main__":
    main()
