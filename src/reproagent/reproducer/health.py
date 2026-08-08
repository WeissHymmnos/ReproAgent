"""复现结果健康度：区分「算出来了」与「空因子/全零指标」。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import polars as pl


def _as_finite_float(x: object) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)  # type: ignore[arg-type]
        if not math.isfinite(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def factor_values_are_usable(
    factor_values: pl.DataFrame | Path | None,
    *,
    min_rows: int = 10,
    min_std: float = 1e-12,
) -> bool:
    """因子值面板非空、有足够行、且截面/时序上非常数。"""
    if factor_values is None:
        return False
    try:
        if isinstance(factor_values, Path):
            if not factor_values.exists():
                return False
            df = pl.read_parquet(factor_values)
        else:
            df = factor_values
    except Exception:  # noqa: BLE001
        return False

    if df is None or df.height < min_rows:
        return False
    if "factor_value" not in df.columns:
        return False
    nn = df.filter(pl.col("factor_value").is_not_null())
    if nn.height < min_rows:
        return False
    std = nn["factor_value"].std()
    std_v = _as_finite_float(std)
    if std_v is None or abs(std_v) < min_std:
        return False
    return True


def metrics_are_non_degenerate(result: Any, *, eps: float = 1e-15) -> bool:
    """拒绝空回测的全零指标（null 因子 drop 后常见）。

    真实弱因子可能 IC≈0，但仍应有非零回撤/换手/分组收益之一。
    全核心指标绝对值为 0 视为未复现成功。
    """
    core = [
        _as_finite_float(getattr(result, "ic_mean", None)),
        _as_finite_float(getattr(result, "ic_ir", None)),
        _as_finite_float(getattr(result, "long_short_annual_return", None)),
        _as_finite_float(getattr(result, "sharpe_ratio", None)),
        _as_finite_float(getattr(result, "max_drawdown", None)),
        _as_finite_float(getattr(result, "turnover", None)),
    ]
    # 任一核心指标为 None → 不健康
    if any(v is None for v in core):
        return False
    if all(abs(v) <= eps for v in core):  # type: ignore[arg-type]
        return False

    groups = getattr(result, "group_annualized_returns", None) or {}
    # 有非零 IC 或有分组收益结构即可；全零且无分组 → 退化
    ic = core[0]
    if abs(ic) <= eps and not groups:  # type: ignore[arg-type]
        return False
    return True


def is_healthy_reproduction(
    result: Any,
    *,
    factor_values: pl.DataFrame | Path | None = None,
) -> bool:
    """回测结果是否可作为成功复现（passed / soft-pass）的前置条件。"""
    path = factor_values
    if path is None:
        path = getattr(result, "factor_values_path", None)
    if not factor_values_are_usable(path):
        return False
    if not metrics_are_non_degenerate(result):
        return False
    return True
