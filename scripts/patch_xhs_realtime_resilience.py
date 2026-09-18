from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_XHS_REALTIME_RESILIENCE_V1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_py(path: Path, text: str) -> None:
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_client(root: Path) -> None:
    path = root / "media_platform/xhs/client.py"
    text = read(path)

    text = text.replace(
        "        timeout=60,  # If media crawling is enabled, Xiaohongshu long videos need longer timeout\n",
        f"        timeout=25,  # bounded realtime HTTP timeout; media download is separate  # {MARKER}\n",
        1,
    )
    text = text.replace("stop=stop_after_attempt(3)", "stop=stop_after_attempt(2)", 1)

    old_block = '''        if response.status_code in {401, 403, 429}:
            raise PlatformAccessError(
                f"XHS request blocked with HTTP {response.status_code}"
            )

        if response.status_code == 471 or response.status_code == 461:
            # someday someone maybe will bypass captcha
            verify_type = response.headers["Verifytype"]
            verify_uuid = response.headers["Verifyuuid"]
            msg = f"CAPTCHA appeared, request failed, Verifytype: {verify_type}, Verifyuuid: {verify_uuid}, Response: {response}"
            utils.logger.error(msg)
            raise Exception(msg)
'''
    new_block = f'''        if response.status_code in {{401, 403, 429}}:
            msg = f"XHS_VERIFY_REQUIRED HTTP {{response.status_code}}"
            utils.logger.error(msg)
            raise PlatformAccessError(msg)

        if response.status_code in {{461, 471}}:
            # {MARKER}: stop cleanly for official verification. No CAPTCHA bypass.
            verify_type = response.headers.get("Verifytype", "")
            msg = f"XHS_VERIFY_REQUIRED CAPTCHA status={{response.status_code}} verify_type={{verify_type}}"
            utils.logger.error(msg)
            raise PlatformAccessError(msg)
'''
    if old_block in text:
        text = text.replace(old_block, new_block, 1)

    old_security = '''        if response_code == str(self.SECURITY_LIMIT_CODE):
            raise PlatformAccessError(
                f"XHS account security restriction, code: {self.SECURITY_LIMIT_CODE}"
            )
'''
    new_security = f'''        if response_code == str(self.SECURITY_LIMIT_CODE):
            msg = f"XHS_VERIFY_REQUIRED account security restriction code={{self.SECURITY_LIMIT_CODE}}"
            utils.logger.error(msg)
            raise PlatformAccessError(msg)
'''
    if old_security in text:
        text = text.replace(old_security, new_security, 1)

    old_pong = '''        except Exception as e:
            utils.logger.error(
                f"[XiaoHongShuClient.pong] Check login state failed: {e}, and try to login again..."
            )
            ping_flag = False
'''
    new_pong = f'''        except (PlatformAccessError, IPBlockError):
            # {MARKER}: an access guard is not a normal login miss. Stop upstream
            # instead of repeatedly navigating/login-probing the account.
            raise
        except Exception as e:
            utils.logger.error(
                f"[XiaoHongShuClient.pong] Check login state failed: {{e}}, and try to login again..."
            )
            ping_flag = False
'''
    if old_pong in text:
        text = text.replace(old_pong, new_pong, 1)

    write_py(path, text)


def patch_core(root: Path) -> None:
    path = root / "media_platform/xhs/core.py"
    text = read(path)

    old_goto = '''            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # Create a client to interact with the Xiaohongshu website.
'''
    new_goto = f'''            self.context_page = await self.browser_context.new_page()
            # {MARKER}: bounded normal navigation only; verification is never bypassed.
            await self.context_page.goto(
                self.index_url, wait_until="domcontentloaded", timeout=20000
            )

            # Create a client to interact with the Xiaohongshu website.
'''
    if old_goto in text:
        text = text.replace(old_goto, new_goto, 1)

    old_items = '''                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
'''
    new_items = f'''                    _promotion_week_xhs_items = list(notes_res.get("items", []) or [])
                    if os.environ.get("PROMOTION_WEEK_XHS_REALTIME_DISCOVERY") == "1":
                        try:
                            _promotion_week_xhs_limit = int(
                                os.environ.get("PROMOTION_WEEK_XHS_REALTIME_ITEMS_PER_KEYWORD", "5")
                            )
                        except Exception:
                            _promotion_week_xhs_limit = 5
                        _promotion_week_xhs_limit = max(1, min(_promotion_week_xhs_limit, 10))
                        _promotion_week_xhs_items = _promotion_week_xhs_items[:_promotion_week_xhs_limit]
                        utils.logger.info(
                            f"[XiaoHongShuCrawler.search] {MARKER} realtime items/keyword="
                            f"{{len(_promotion_week_xhs_items)}}"
                        )
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
'''
    if old_items in text and "_promotion_week_xhs_items" not in text:
        text = text.replace(old_items, new_items, 1)
        text = text.replace(
            '                        ) for post_item in notes_res.get("items", {}) if post_item.get("model_type") not in ("rec_query", "hot_query")\n',
            '                        ) for post_item in _promotion_week_xhs_items if post_item.get("model_type") not in ("rec_query", "hot_query")\n',
            1,
        )

    old_access = '''            except (IPBlockError, PlatformAccessError) as ex:
                # Access restricted (IP block / rate limit / account security).
                # Skip this note instead of aborting the whole asyncio.gather batch.
                utils.logger.error(
                    f"[XiaoHongShuCrawler.get_note_detail_async_task] Access restricted while getting note {note_id}: {ex}. "
                    f"建议降低采集频率、更换 IP 或检查账号状态"
                )
                return None
'''
    new_access = f'''            except (IPBlockError, PlatformAccessError) as ex:
                # {MARKER}: stop the current run on an explicit access guard rather
                # than continuing to hit more note details.
                utils.logger.error(
                    f"[XiaoHongShuCrawler.get_note_detail_async_task] XHS_VERIFY_REQUIRED: {{ex}}"
                )
                raise
'''
    if old_access in text:
        text = text.replace(old_access, new_access, 1)

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/xhs/client.py"
    core = root / "media_platform/xhs/core.py"
    result = {
        "patch_version": 1,
        "client_exists": client.exists(),
        "core_exists": core.exists(),
        "bounded_http_timeout": False,
        "bounded_retry": False,
        "access_guard": False,
        "pong_guard_propagation": False,
        "bounded_navigation": False,
        "realtime_items_per_keyword": False,
        "detail_guard_propagation": False,
        "ok": False,
    }
    if not client.exists() or not core.exists():
        return result
    try:
        client_text = read(client)
        core_text = read(core)
        ast.parse(client_text, filename=str(client))
        ast.parse(core_text, filename=str(core))
        result["bounded_http_timeout"] = "timeout=25" in client_text
        result["bounded_retry"] = "stop=stop_after_attempt(2)" in client_text
        result["access_guard"] = "XHS_VERIFY_REQUIRED" in client_text
        result["pong_guard_propagation"] = "except (PlatformAccessError, IPBlockError):" in client_text
        result["bounded_navigation"] = 'wait_until="domcontentloaded", timeout=20000' in core_text
        result["realtime_items_per_keyword"] = (
            "PROMOTION_WEEK_XHS_REALTIME_DISCOVERY" in core_text
            and "PROMOTION_WEEK_XHS_REALTIME_ITEMS_PER_KEYWORD" in core_text
        )
        result["detail_guard_propagation"] = "XHS_VERIFY_REQUIRED" in core_text and "raise\n" in core_text
        result["ok"] = all(result[k] for k in (
            "bounded_http_timeout",
            "bounded_retry",
            "access_guard",
            "pong_guard_propagation",
            "bounded_navigation",
            "realtime_items_per_keyword",
            "detail_guard_propagation",
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Bound XHS realtime discovery and stop cleanly on official verification/rate limits.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        if not args.check:
            patch_client(root)
            patch_core(root)
        result = check(root)
    except Exception as exc:
        print(json.dumps({"ok": False, "root": str(root), "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"root": str(root), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
