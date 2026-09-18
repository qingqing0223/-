from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

MARKER = "PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V3"


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
    path = root / "media_platform/weibo/client.py"
    text = read(path)
    text = text.replace("PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V1", MARKER)
    text = text.replace("PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V2", MARKER)
    text = text.replace(
        "if response.status_code in {418, 429, 432}:",
        "if response.status_code in {403, 418, 429, 432}:",
    )

    if "retry_if_not_exception_type" not in text:
        text = text.replace(
            "from tenacity import retry, stop_after_attempt, wait_fixed\n",
            "from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed\n",
            1,
        )

    exception_anchor = "from .exception import DataFetchError\n"
    guard_def = (
        f"\n\nclass WeiboAccessGuardError(DataFetchError):\n"
        f"    \"\"\"Stop immediately on public anti-abuse/verification responses.  # {MARKER}\"\"\"\n"
        "    pass\n"
    )
    if "class WeiboAccessGuardError" not in text:
        text = replace_once(
            text,
            exception_anchor,
            exception_anchor + guard_def,
            "weibo access-guard exception",
        )

    text = text.replace(
        "        timeout=60,  # If media crawling is enabled, Weibo images need a longer timeout\n",
        f"        timeout=25,  # bounded realtime HTTP timeout; media download is separate  # {MARKER}\n",
        1,
    )

    old_decorator = "    @retry(stop=stop_after_attempt(5), wait=wait_fixed(3))\n"
    new_decorator = (
        f"    @retry(  # {MARKER}\n"
        "        stop=stop_after_attempt(2),\n"
        "        wait=wait_fixed(2),\n"
        "        retry=retry_if_not_exception_type(WeiboAccessGuardError),\n"
        "        reraise=True,\n"
        "    )\n"
    )
    if old_decorator in text:
        text = text.replace(old_decorator, new_decorator, 1)

    request_anchor = (
        "        async with make_async_client(proxy=self.proxy) as client:\n"
        "            response = await client.request(method, url, timeout=self.timeout, **kwargs)\n\n"
        "        if enable_return_response:\n"
    )
    if "WEIBO_VERIFY_REQUIRED" not in text:
        request_block = (
            "        async with make_async_client(proxy=self.proxy) as client:\n"
            "            response = await client.request(method, url, timeout=self.timeout, **kwargs)\n\n"
            f"        # {MARKER}: do not hammer Weibo when it explicitly asks for verification\n"
            "        # or rate-limits the current session. Human recovery/cooldown is required.\n"
            "        if response.status_code in {403, 418, 429, 432}:\n"
            "            utils.logger.error(\n"
            "                f\"[WeiboClient.request] WEIBO_VERIFY_REQUIRED status={response.status_code}; \"\n"
            "                \"automatic retry stopped\"\n"
            "            )\n"
            "            raise WeiboAccessGuardError(f\"WEIBO_VERIFY_REQUIRED status={response.status_code}\")\n\n"
            "        if enable_return_response:\n"
        )
        text = replace_once(text, request_anchor, request_block, "weibo status guard")

    old_json_error = (
        "        except json.decoder.JSONDecodeError:\n"
        "            # issue: #771 Search API returns error 432, retry multiple times + update h5 cookies\n"
        "            utils.logger.error(f\"[WeiboClient.request] request {method}:{url} err code: {response.status_code} res:{response.text}\")\n"
        "            await self.playwright_page.goto(self._host)\n"
        "            await asyncio.sleep(2)\n"
        "            await self.update_cookies(browser_context=self.playwright_page.context)\n"
        "            raise DataFetchError(f\"get response code error: {response.status_code}\")\n"
    )
    new_json_error = (
        "        except json.decoder.JSONDecodeError:\n"
        f"            # {MARKER}: an empty/non-JSON 200 is a common risk-control response.\n"
        "            # Do not repeatedly navigate/reload the site; stop this candidate and cool down.\n"
        "            utils.logger.error(\n"
        "                f\"[WeiboClient.request] WEIBO_VERIFY_REQUIRED non_json_response \"\n"
        "                f\"status={response.status_code} body_len={len(response.text or '')}\"\n"
        "            )\n"
        "            raise WeiboAccessGuardError(\n"
        "                f\"WEIBO_VERIFY_REQUIRED non_json_response status={response.status_code}\"\n"
        "            )\n"
    )
    if old_json_error in text:
        text = text.replace(old_json_error, new_json_error, 1)

    old_ok0 = (
        "        if ok_code == 0:  # response error\n"
        "            utils.logger.error(f\"[WeiboClient.request] request {method}:{url} err, res:{data}\")\n"
        "            raise DataFetchError(data.get(\"msg\", \"response error\"))\n"
    )
    new_ok0 = (
        "        if ok_code == 0:  # response error\n"
        "            utils.logger.error(f\"[WeiboClient.request] request {method}:{url} err, res:{data}\")\n"
        "            _wb_msg = str(data.get(\"msg\", \"response error\"))\n"
        "            if any(token in _wb_msg for token in (\"频繁\", \"验证\", \"异常\", \"安全\", \"访问受限\")):\n"
        "                utils.logger.error(\"[WeiboClient.request] WEIBO_VERIFY_REQUIRED response_message\")\n"
        "                raise WeiboAccessGuardError(f\"WEIBO_VERIFY_REQUIRED {_wb_msg}\")\n"
        "            raise DataFetchError(_wb_msg)\n"
    )
    if old_ok0 in text:
        text = text.replace(old_ok0, new_ok0, 1)

    old_pong_except = (
        "        except Exception as e:\n"
        "            utils.logger.error(f\"[WeiboClient.pong] Pong weibo failed: {e}, and try to login again...\")\n"
        "            ping_flag = False\n"
    )
    new_pong_except = (
        f"        except WeiboAccessGuardError:\n"
        f"            # {MARKER}: verification/rate-limit is not a login failure; stop upstream.\n"
        "            raise\n"
        "        except Exception as e:\n"
        "            utils.logger.error(f\"[WeiboClient.pong] Pong weibo failed: {e}, and try to login again...\")\n"
        "            ping_flag = False\n"
    )
    if old_pong_except in text:
        text = text.replace(old_pong_except, new_pong_except, 1)

    write_py(path, text)


def patch_core(root: Path) -> None:
    path = root / "media_platform/weibo/core.py"
    text = read(path).replace("PROMOTION_WEEK_WB_REALTIME_RESILIENCE_V1", MARKER)

    if "from .client import WeiboClient, WeiboAccessGuardError" not in text:
        text = text.replace(
            "from .client import WeiboClient\n",
            "from .client import WeiboClient, WeiboAccessGuardError\n",
            1,
        )

    old_goto = (
        "            self.context_page = await self.browser_context.new_page()\n"
        "            await self.context_page.goto(self.index_url)\n"
        "            await asyncio.sleep(2)\n"
    )
    new_goto = (
        "            self.context_page = await self.browser_context.new_page()\n"
        f"            # {MARKER}: bounded normal navigation, no verification bypass.\n"
        "            try:\n"
        "                await self.context_page.goto(\n"
        "                    self.index_url, wait_until=\"domcontentloaded\", timeout=20000\n"
        "                )\n"
        "            except Exception as _wb_nav_exc:\n"
        "                utils.logger.warning(\n"
        "                    f\"[WeiboCrawler.start] desktop navigation failed, trying mobile homepage once: {_wb_nav_exc}\"\n"
        "                )\n"
        "                await self.context_page.goto(\n"
        "                    self.mobile_index_url, wait_until=\"domcontentloaded\", timeout=20000\n"
        "                )\n"
        "            await asyncio.sleep(2)\n"
    )
    if old_goto in text:
        text = text.replace(old_goto, new_goto, 1)

    # Verification/rate-limit raised by the client must escape the per-note
    # comment worker.  Swallowing it as a generic DataFetchError would cause the
    # current batch to keep hitting Weibo after the platform explicitly asked us
    # to stop.
    old_comment_except = (
        "            except DataFetchError as ex:\n"
        "                utils.logger.error(f\"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}\")\n"
    )
    new_comment_except = (
        f"            except WeiboAccessGuardError as ex:\n"
        f"                utils.logger.error(f\"[WeiboCrawler.get_note_comments] WB_DETAIL_VERIFY_STOP: {{ex}}\")\n"
        "                raise\n"
        "            except DataFetchError as ex:\n"
        "                utils.logger.error(f\"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}\")\n"
    )
    if old_comment_except in text:
        text = text.replace(old_comment_except, new_comment_except, 1)

    # Bound the post-login mobile navigation as well. This is normal navigation
    # only; no verification/captcha bypass is attempted.
    old_mobile_goto = (
        "                await self.context_page.goto(self.mobile_index_url)\n"
        "                await asyncio.sleep(3)\n"
    )
    new_mobile_goto = (
        f"                # {MARKER}: bounded post-login mobile navigation.\n"
        "                await self.context_page.goto(\n"
        "                    self.mobile_index_url, wait_until=\"domcontentloaded\", timeout=20000\n"
        "                )\n"
        "                await asyncio.sleep(3)\n"
    )
    if old_mobile_goto in text:
        text = text.replace(old_mobile_goto, new_mobile_goto, 1)

    full_text_anchor = (
        "    async def batch_get_notes_full_text(self, note_list: List[Dict]) -> List[Dict]:\n"
        "        \"\"\"\n"
    )
    if 'os.environ.get("PROMOTION_WEEK_WB_REALTIME")' not in text:
        # Insert after the docstring block using a stable functional anchor.
        old_check = (
            "        if not config.ENABLE_WEIBO_FULL_TEXT:\n"
            "            return note_list\n\n"
            "        result = []\n"
        )
        new_check = (
            f"        # {MARKER}: search snippets are sufficient for five-minute discovery.\n"
            "        # Full-text detail enrichment belongs to the separate historical/backfill path.\n"
            "        if os.environ.get(\"PROMOTION_WEEK_WB_REALTIME\") == \"1\":\n"
            "            return note_list\n"
            "        if not config.ENABLE_WEIBO_FULL_TEXT:\n"
            "            return note_list\n\n"
            "        result = []\n"
        )
        text = replace_once(text, old_check, new_check, "weibo realtime full-text skip")

    write_py(path, text)


def check(root: Path) -> dict:
    client = root / "media_platform/weibo/client.py"
    core = root / "media_platform/weibo/core.py"
    result = {
        "patch_version": 3,
        "client_exists": client.exists(),
        "core_exists": core.exists(),
        "bounded_http_timeout": False,
        "bounded_retry": False,
        "access_guard": False,
        "non_json_guard": False,
        "forbidden_guard": False,
        "bounded_navigation": False,
        "realtime_full_text_skip": False,
        "pong_guard_propagation": False,
        "comment_guard_propagation": False,
        "post_login_navigation_bounded": False,
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
        result["bounded_retry"] = "stop=stop_after_attempt(2)" in client_text and "retry_if_not_exception_type" in client_text
        result["access_guard"] = "class WeiboAccessGuardError" in client_text and "WEIBO_VERIFY_REQUIRED status=" in client_text
        result["non_json_guard"] = "WEIBO_VERIFY_REQUIRED non_json_response" in client_text
        result["forbidden_guard"] = "response.status_code in {403, 418, 429, 432}" in client_text
        result["bounded_navigation"] = 'wait_until="domcontentloaded", timeout=20000' in core_text
        result["realtime_full_text_skip"] = 'os.environ.get("PROMOTION_WEEK_WB_REALTIME") == "1"' in core_text
        result["pong_guard_propagation"] = "except WeiboAccessGuardError:" in client_text
        result["comment_guard_propagation"] = (
            "WB_DETAIL_VERIFY_STOP" in core_text
            and "from .client import WeiboClient, WeiboAccessGuardError" in core_text
        )
        result["post_login_navigation_bounded"] = (
            'self.mobile_index_url, wait_until="domcontentloaded", timeout=20000' in core_text
        )
        result["ok"] = all((
            result["bounded_http_timeout"],
            result["bounded_retry"],
            result["access_guard"],
            result["non_json_guard"],
            result["forbidden_guard"],
            result["bounded_navigation"],
            result["realtime_full_text_skip"],
            result["pong_guard_propagation"],
            result["comment_guard_propagation"],
            result["post_login_navigation_bounded"],
        ))
    except Exception:
        pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Make Weibo realtime collection bounded and stop cleanly on anti-abuse verification.")
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
