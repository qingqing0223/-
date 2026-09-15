from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

TARGET = Path(r"E:\MediaCrawler_clean\media_platform\xhs\core.py")
MARKER = "MANUAL_CAPTCHA_WAIT_PATCH_V1"

OLD = '''                except DataFetchError:\n                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")\n                    break\n'''

NEW = '''                except DataFetchError:\n                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")\n                    break\n                except Exception as ex:\n                    # MANUAL_CAPTCHA_WAIT_PATCH_V1\n                    # Do not bypass Xiaohongshu verification. Keep the browser open so\n                    # the operator can complete the official slider/CAPTCHA manually,\n                    # then retry the same search page.\n                    msg = str(ex)\n                    if "CAPTCHA appeared" not in msg and "Verifytype" not in msg:\n                        raise\n                    utils.logger.warning(\n                        "[XiaoHongShuCrawler.search] CAPTCHA/verification detected. "\n                        "Please finish the official verification manually in the open browser. "\n                        "Waiting up to 180 seconds before retrying this page..."\n                    )\n                    verification_markers = (\n                        "请通过验证", "拖动滑块", "安全验证", "完成验证",\n                        "请完成验证", "验证后继续",\n                    )\n                    verified = False\n                    clear_streak = 0\n                    for _ in range(180):\n                        await asyncio.sleep(1)\n                        try:\n                            html = await self.context_page.content()\n                            visible_verification = any(marker in html for marker in verification_markers)\n                            if visible_verification:\n                                clear_streak = 0\n                                continue\n                            clear_streak += 1\n                            if clear_streak >= 2:\n                                await self.xhs_client.update_cookies(\n                                    browser_context=self.browser_context,\n                                    urls=self.cookie_urls,\n                                )\n                                verified = True\n                                break\n                        except Exception:\n                            clear_streak = 0\n                    if verified:\n                        utils.logger.info(\n                            "[XiaoHongShuCrawler.search] Manual verification appears complete; "\n                            "retrying the same search page."\n                        )\n                        continue\n                    utils.logger.error(\n                        "[XiaoHongShuCrawler.search] Manual verification was not completed within 180 seconds; "\n                        "stopping this run without bypassing verification."\n                    )\n                    break\n'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("XHS manual verification wait patch is already installed.")
        print(f"Target: {TARGET}")
        return

    if OLD not in text:
        raise SystemExit(
            "Patch anchor not found. MediaCrawler core.py differs from the expected version; "
            "no changes were made."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".bak_manual_verify_{stamp}")
    shutil.copy2(TARGET, backup)

    patched = text.replace(OLD, NEW, 1)
    TARGET.write_text(patched, encoding="utf-8")

    print("XHS manual verification wait patch installed successfully.")
    print(f"Backup: {backup}")
    print(f"Target: {TARGET}")
    print("Behavior: when XHS returns a CAPTCHA challenge, the browser stays open for up to 180s")
    print("for manual completion, then the same search page is retried. No CAPTCHA bypass is performed.")


if __name__ == "__main__":
    main()
