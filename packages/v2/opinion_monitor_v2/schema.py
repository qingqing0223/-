"""Stable input/output contract for the fixed v2.1 taxonomy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


TYPE_BY_STATUS: dict[str, frozenset[str | None]] = {
    "normal": frozenset({"support"}),
    "neutral": frozenset({None}),
    "attention": frozenset({"information_gap", "consultation"}),
    "problematic": frozenset({
        "concern", "criticism", "skepticism", "implementation_issue",
        "fairness_dispute", "complaint_rights", "discriminatory_expression",
    }),
}


class InputError(ValueError):
    """Input record does not satisfy the public API contract."""


class ClassificationError(ValueError):
    """Model output is not a valid status/type classification."""


class APIError(RuntimeError):
    """Remote API request failed; status may be available for diagnostics."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ClassificationResult:
    """The task output: exactly one status and its legal subtype."""

    status: str
    type: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"status": self.status, "type": self.type}


def validate_output(value: Any) -> ClassificationResult:
    if not isinstance(value, dict) or set(value) != {"status", "type"}:
        raise ClassificationError("output must be a JSON object with exactly status and type")
    status = value.get("status")
    subtype = value.get("type")
    if not isinstance(status, str) or status not in TYPE_BY_STATUS:
        raise ClassificationError(f"invalid status: {status!r}")
    if subtype is not None and not isinstance(subtype, str):
        raise ClassificationError(f"type must be a string or null, got {type(subtype).__name__}")
    if subtype not in TYPE_BY_STATUS[status]:
        raise ClassificationError(f"type {subtype!r} is not legal for status {status!r}")
    return ClassificationResult(status=status, type=subtype)


def parse_model_output(raw: str) -> ClassificationResult:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClassificationError(f"model did not return valid JSON: {exc.msg}") from exc
    return validate_output(value)
