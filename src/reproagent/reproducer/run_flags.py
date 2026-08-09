"""Per-run observability flags for fallback / soft-pass (auditable scoring)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_RUN_FLAGS: ContextVar[dict[str, Any] | None] = ContextVar("reproagent_run_flags", default=None)


def begin_run_flags() -> dict[str, Any]:
    flags: dict[str, Any] = {
        "formula_fallback": False,
        "universe_fallback": False,
        "universe_fallback_reason": None,
        "soft_pass": False,
    }
    _RUN_FLAGS.set(flags)
    return flags


def get_run_flags() -> dict[str, Any]:
    flags = _RUN_FLAGS.get()
    if flags is None:
        return begin_run_flags()
    return flags


def mark_formula_fallback(reason: str = "") -> None:
    flags = get_run_flags()
    flags["formula_fallback"] = True
    if reason:
        flags["formula_fallback_reason"] = reason


def mark_universe_fallback(reason: str = "") -> None:
    flags = get_run_flags()
    flags["universe_fallback"] = True
    flags["universe_fallback_reason"] = reason or flags.get("universe_fallback_reason")


def mark_soft_pass() -> None:
    flags = get_run_flags()
    flags["soft_pass"] = True


def snapshot_run_flags() -> dict[str, Any]:
    return dict(get_run_flags())
