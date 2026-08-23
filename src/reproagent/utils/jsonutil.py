"""JSON helpers: finite numbers only (NaN/Inf are not valid JSON)."""

from __future__ import annotations

import json
import math
from typing import Any


def json_ready(obj: Any) -> Any:
    """Replace non-finite floats with None so dumps() is spec-compliant JSON."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    return obj


def dumps(obj: Any, *, indent: int | None = None) -> str:
    """Serialize pipeline / job payloads without emitting NaN or Infinity."""
    return json.dumps(json_ready(obj), ensure_ascii=False, default=str, indent=indent)
