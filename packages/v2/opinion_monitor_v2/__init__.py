"""Public opinion monitor v2.1: fixed taxonomy, status/type only."""

from .client import OpinionMonitorV2
from .schema import (
    APIError,
    ClassificationError,
    ClassificationResult,
    InputError,
    TYPE_BY_STATUS,
)

__all__ = [
    "OpinionMonitorV2",
    "ClassificationResult",
    "ClassificationError",
    "APIError",
    "InputError",
    "TYPE_BY_STATUS",
]
