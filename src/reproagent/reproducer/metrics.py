"""指标提取与图表生成。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from reproagent.models.backtest import BacktestResult


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce polars scalar aggregates to float for typing and safety.

    NaN/Inf → default，避免 ic_mean=nan 把健康复现打成 unhealthy。
    """
    import math

    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def compute_ic(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
) -> pl.DataFrame:
    """截面 rank IC（按日期），返回 [date, ic]（丢弃单日 nan corr）。"""
    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()
    ic_df = (
        df.group_by("date")
        .agg(pl.corr("factor_value", "forward_return", method="spearman").alias("ic"))
        .sort("date")
    )
    # 全日因子常数 / 样本过少时 spearman 为 null/nan，不参与均值
    if "ic" in ic_df.columns:
        ic_df = ic_df.filter(pl.col("ic").is_not_null() & pl.col("ic").is_finite())
    return ic_df


def compute_group_returns(
    grouped: pl.DataFrame,
    returns: pl.DataFrame,
    num_groups: int,
) -> dict[int, float]:
    """计算各分组年化收益。"""
    df = grouped.join(returns, on=["date", "asset"], how="inner")
    daily_group_ret = df.group_by(["date", "group"]).agg(
        pl.col("forward_return").mean().alias("daily_return")
    )
    ann_ret = (
        daily_group_ret.group_by("group")
        .agg((pl.col("daily_return").mean() * 252).alias("ann_return"))
        .sort("group")
    )
    return dict(zip(ann_ret["group"].to_list(), ann_ret["ann_return"].to_list()))


def compute_sharpe(returns: pl.Series, freq: str = "daily") -> float:
    """夏普比率；日频年化因子 √252。"""
    if len(returns) == 0:
        return 0.0
    std = _as_float(returns.std())
    mean = _as_float(returns.mean())
    if std == 0.0:
        return 0.0
    ann_factor = 252**0.5 if freq == "daily" else 1.0
    return (mean / std) * ann_factor


def compute_max_drawdown(equity_curve: pl.Series) -> float:
    """最大回撤。"""
    if len(equity_curve) == 0:
        return 0.0
    cum_max = equity_curve.cum_max()
    drawdown = (equity_curve - cum_max) / cum_max
    return abs(_as_float(drawdown.min()))


def generate_charts(
    backtest_result: BacktestResult,
    output_dir: Path,
) -> list[Path]:
    """生成净值曲线、分组收益、IC 时序图，返回图片路径。"""
    from reproagent.utils.plotting import (
        save_equity_curve_chart,
        save_group_returns_chart,
        save_ic_timeseries_chart,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    if backtest_result.group_annualized_returns:
        p = save_group_returns_chart(
            backtest_result.group_annualized_returns, output_dir / "group_returns.png"
        )
        paths.append(p)

    if backtest_result.equity_curve_path.exists():
        df = pl.read_parquet(backtest_result.equity_curve_path)
        if "date" in df.columns and "ls_return" in df.columns:
            equity = (1 + df["ls_return"]).cum_prod()
            equity_dict = dict(zip(df["date"].to_list(), equity.to_list()))
            p = save_equity_curve_chart(equity_dict, output_dir / "equity_curve.png")
            paths.append(p)

    factor_values_dir = backtest_result.factor_values_path.parent
    ic_path = factor_values_dir / "ic.parquet"
    if ic_path.exists():
        df = pl.read_parquet(ic_path)
        if "date" in df.columns and "ic" in df.columns:
            ic_dict = dict(zip(df["date"].to_list(), df["ic"].to_list()))
            p = save_ic_timeseries_chart(ic_dict, output_dir / "ic_timeseries.png")
            paths.append(p)

    return paths


def compute_alpha_decay(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
    lags: list[int] | None = None,
) -> dict[int, float]:
    """前向多滞后期 Rank IC 衰减曲线。

    对每个 lag，用 factor_value(t) 预测 forward_return(t+lag)，
    计算截面的平均 Rank IC。

    Returns
    -------
    dict[int, float]: {lag_days: mean_rank_ic}
    """
    if lags is None:
        lags = [1, 2, 3, 5, 10, 20]

    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()
    df = df.sort(["asset", "date"])

    result: dict[int, float] = {}
    for lag in lags:
        lagged = df.with_columns(
            pl.col("forward_return").shift(-lag).over("asset").alias(f"fwd_lag{lag}")
        ).drop_nulls(f"fwd_lag{lag}")

        if lagged.is_empty():
            result[lag] = 0.0
            continue

        ic_df = (
            lagged.group_by("date")
            .agg(pl.corr("factor_value", f"fwd_lag{lag}", method="spearman").alias("ic"))
            .drop_nulls("ic")
        )
        result[lag] = _as_float(ic_df["ic"].mean()) if len(ic_df) > 0 else 0.0

    return result


def compute_monotonicity(
    grouped_returns: pl.DataFrame,
) -> float:
    """分组收益单调性：Kendall tau between (group_rank, group_mean_return) per date。

    Parameters
    ----------
    grouped_returns: 含 date, group (int), daily_return 列

    Returns
    -------
    float: 逐日 Kendall tau 的截面均值（无偏见 0）
    """
    if grouped_returns.is_empty():
        return 0.0

    if "group" not in grouped_returns.columns or "daily_return" not in grouped_returns.columns:
        return 0.0

    import numpy as np
    from scipy.stats import kendalltau

    dates = grouped_returns["date"].unique().to_list()
    taus: list[float] = []
    for d in dates:
        ddf = grouped_returns.filter(pl.col("date") == d)
        if len(ddf) < 2:
            continue
        groups = ddf["group"].to_list()
        returns = ddf["daily_return"].to_list()
        tau, _ = kendalltau(groups, returns)
        if not np.isnan(tau):
            taus.append(tau)

    return float(np.mean(taus)) if taus else 0.0


def compute_half_life(ic_series: dict[int, float]) -> float:
    """从 alpha decay 曲线估算因子半衰期（Rank IC 衰减到初始值一半的天数）。

    使用指数衰减拟合：IC(lag) ≈ IC₀ * exp(-lag / τ)
    """
    if not ic_series:
        return 0.0

    import numpy as np

    lags = sorted(ic_series.keys())
    ic_values = [ic_series[lag] for lag in lags]
    ic0 = abs(ic_values[0]) if ic_values[0] != 0 else 1.0

    # 找第一个 |IC| < |IC₀|/2 的 lag
    half_threshold = ic0 / 2.0
    for lag, ic in zip(lags, ic_values):
        if abs(ic) < half_threshold:
            return float(lag)

    # 如果未衰减到一半，做指数拟合估算
    if len(lags) >= 2:
        log_values = [np.log(max(abs(v), 1e-10)) for v in ic_values]
        if len(set(lags)) >= 2:
            slope, _ = np.polyfit(lags, log_values, 1)
            if abs(slope) > 1e-10:
                return float(-np.log(2) / slope)

    return float(len(lags))
