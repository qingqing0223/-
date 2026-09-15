"""Standalone OpenAI-compatible API client for the v2.1 public-opinion task."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from typing import Mapping, Sequence

from .schema import APIError, ClassificationError, ClassificationResult, InputError, parse_model_output


DEFAULT_MODEL = "qwen3.8-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PROMPT_FILE = "prompts_v2_1.json"


class OpinionMonitorV2:
    """One-record or batch public-opinion classification using a fixed taxonomy.

    API credentials are resolved at construction time and never included in repr,
    outputs, prompts, exceptions, or package files.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "DASHSCOPE_API_KEY",
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 180,
        retries: int = 2,
        max_tokens: int = 1024,
        concurrency: int = 4,
    ) -> None:
        secret = api_key if api_key is not None else os.environ.get(api_key_env)
        if not secret or not secret.strip():
            raise InputError(f"API Key missing: pass api_key or set {api_key_env}")
        if timeout <= 0 or retries < 0 or max_tokens < 1 or concurrency < 1:
            raise InputError("timeout/max_tokens/concurrency must be positive and retries non-negative")
        self._api_key = secret.strip()
        self.api_key_env = api_key_env
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.max_tokens = max_tokens
        self.concurrency = concurrency
        self._endpoint = self._make_endpoint(self.base_url)
        self._prompt = json.loads(files("opinion_monitor_v2").joinpath(PROMPT_FILE).read_text(encoding="utf-8"))

    def __repr__(self) -> str:
        return f"OpinionMonitorV2(model={self.model!r}, base_url={self.base_url!r}, api_key=[REDACTED])"

    @property
    def prompt_version(self) -> str:
        return str(self._prompt["version"])

    @staticmethod
    def _make_endpoint(base_url: str) -> str:
        if not base_url.startswith("https://"):
            raise InputError("base_url must use HTTPS")
        return base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"

    @staticmethod
    def _validate_input(content: str, context: str | None) -> tuple[str, str]:
        if not isinstance(content, str) or not content.strip():
            raise InputError("content must be a non-empty string")
        if context is not None and not isinstance(context, str):
            raise InputError("context must be a string or None")
        return content, context or "（无）"

    def _messages(self, content: str, context: str | None) -> list[dict[str, str]]:
        content, context = self._validate_input(content, context)
        user = self._prompt["user_prompt"].format(content=content, context=context)
        return [
            {"role": "system", "content": self._prompt["system_prompt"]},
            {"role": "user", "content": user},
        ]

    def _request_once(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ClassificationError("API returned an empty model message")
            return content
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:1000]
            error_body = error_body.replace(self._api_key, "[REDACTED]")
            raise APIError(f"HTTP {exc.code}: {error_body}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            detail = str(exc.reason).replace(self._api_key, "[REDACTED]")
            raise APIError(f"network error: {detail}") from exc
        except TimeoutError as exc:
            raise APIError("network timeout") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise APIError(f"API response envelope invalid: {type(exc).__name__}") from exc

    def classify(self, content: str, context: str | None = None) -> ClassificationResult:
        """Return exactly one legal status/type result; failures raise exceptions."""
        messages = self._messages(content, context)
        for attempt in range(self.retries + 1):
            try:
                return parse_model_output(self._request_once(messages))
            except APIError as exc:
                retryable = exc.status is None or exc.status in (408, 429) or exc.status >= 500
                if not retryable or attempt >= self.retries:
                    raise
                time.sleep(min(2**attempt, 8))
        raise AssertionError("unreachable retry state")

    def classify_many(self, records: Sequence[Mapping[str, object]], *,
                      concurrency: int | None = None) -> list[ClassificationResult]:
        """Classify records concurrently while returning results in input order.

        Only `content` and `context` are sent to the model; IDs, metadata and
        Ground Truth-like fields in a record are not included in API messages.
        """
        workers = self.concurrency if concurrency is None else concurrency
        if workers < 1:
            raise InputError("concurrency must be positive")
        inputs = []
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise InputError(f"record {index} must be a mapping")
            content = record.get("content")
            context = record.get("context")
            self._validate_input(content, context)
            inputs.append((content, context))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda item: self.classify(*item), inputs))
