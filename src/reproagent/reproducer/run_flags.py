"""Per-run observability flags for fallback / proxy (auditable scoring)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_RUN_FLAGS: ContextVar[dict[str, Any] | None] = ContextVar("reproagent_run_flags", default=None)


def begin_run_flags() -> dict[str, Any]:
    flags: dict[str, Any] = {
        "formula_fallback": False,
        "formula_proxy": False,
        "universe_fallback": False,
        "universe_fallback_reason": None,
        "soft_pass": False,
        "proxy_factors": [],
        "recovery_used": False,
        "recovery_reasons": [],
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


def mark_formula_proxy(factor_name: str = "", reason: str = "") -> None:
    """整式代理（close/市值启发式）— 计入无回退失败。"""
    flags = get_run_flags()
    flags["formula_proxy"] = True
    flags["formula_fallback"] = True  # 代理 = 回退
    if factor_name:
        lst = flags.setdefault("proxy_factors", [])
        if factor_name not in lst:
            lst.append(factor_name)
    if reason:
        flags["formula_proxy_reason"] = reason


def mark_universe_fallback(reason: str = "") -> None:
    flags = get_run_flags()
    flags["universe_fallback"] = True
    flags["universe_fallback_reason"] = reason or flags.get("universe_fallback_reason")


def mark_soft_pass() -> None:
    flags = get_run_flags()
    flags["soft_pass"] = True


def mark_recovery_used(reason: str = "") -> None:
    """开发恢复路径（domain/force/keep-first 等）— 严格评分一律计失败。"""
    flags = get_run_flags()
    flags["recovery_used"] = True
    flags["formula_proxy"] = True
    flags["formula_fallback"] = True
    if reason:
        lst = flags.setdefault("recovery_reasons", [])
        if reason not in lst:
            lst.append(reason)


def snapshot_run_flags() -> dict[str, Any]:
    return dict(get_run_flags())


def restore_run_flags(snapshot: dict[str, Any]) -> None:
    """用快照覆盖当前 flags（dry-run 不得污染主流程 observability）。"""
    flags = get_run_flags()
    flags.clear()
    flags.update(
        {
            "formula_fallback": bool(snapshot.get("formula_fallback", False)),
            "formula_proxy": bool(snapshot.get("formula_proxy", False)),
            "universe_fallback": bool(snapshot.get("universe_fallback", False)),
            "universe_fallback_reason": snapshot.get("universe_fallback_reason"),
            "soft_pass": bool(snapshot.get("soft_pass", False)),
            "proxy_factors": list(snapshot.get("proxy_factors") or []),
            "recovery_used": bool(snapshot.get("recovery_used", False)),
            "recovery_reasons": list(snapshot.get("recovery_reasons") or []),
        }
    )
    for k, v in snapshot.items():
        if k not in flags:
            flags[k] = v
