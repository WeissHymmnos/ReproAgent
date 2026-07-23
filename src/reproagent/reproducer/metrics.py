"""指标提取与图表生成。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from reproagent.models.backtest import BacktestResult


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce polars scalar aggregates to float for typing and safety."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_ic(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
) -> pl.DataFrame:
    """截面 rank IC（按日期），返回 [date, ic]。"""
    df = factor_values.join(forward_returns, on=['date', 'asset'], how='inner').drop_nulls()
    ic_df = df.group_by('date').agg(
        pl.corr('factor_value', 'forward_return', method='spearman').alias('ic')
    ).sort('date')
    return ic_df


def compute_group_returns(
    grouped: pl.DataFrame,
    returns: pl.DataFrame,
    num_groups: int,
) -> dict[int, float]:
    """计算各分组年化收益。"""
    df = grouped.join(returns, on=['date', 'asset'], how='inner')
    daily_group_ret = df.group_by(['date', 'group']).agg(
        pl.col('forward_return').mean().alias('daily_return')
    )
    ann_ret = daily_group_ret.group_by('group').agg(
        (pl.col('daily_return').mean() * 252).alias('ann_return')
    ).sort('group')
    return dict(zip(ann_ret['group'].to_list(), ann_ret['ann_return'].to_list()))


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
            backtest_result.group_annualized_returns,
            output_dir / "group_returns.png"
        )
        paths.append(p)
        
    if backtest_result.equity_curve_path.exists():
        df = pl.read_parquet(backtest_result.equity_curve_path)
        if 'date' in df.columns and 'ls_return' in df.columns:
            equity = (1 + df['ls_return']).cum_prod()
            equity_dict = dict(zip(df['date'].to_list(), equity.to_list()))
            p = save_equity_curve_chart(
                equity_dict,
                output_dir / "equity_curve.png"
            )
            paths.append(p)
            
    factor_values_dir = backtest_result.factor_values_path.parent
    ic_path = factor_values_dir / "ic.parquet"
    if ic_path.exists():
        df = pl.read_parquet(ic_path)
        if 'date' in df.columns and 'ic' in df.columns:
            ic_dict = dict(zip(df['date'].to_list(), df['ic'].to_list()))
            p = save_ic_timeseries_chart(
                ic_dict,
                output_dir / "ic_timeseries.png"
            )
            paths.append(p)
            
    return paths
