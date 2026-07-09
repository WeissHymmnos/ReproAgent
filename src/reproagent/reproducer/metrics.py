"""指标提取与图表生成。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from reproagent.models.backtest import BacktestResult


def compute_ic(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
) -> pl.DataFrame:
    """截面 rank IC（按日期），返回 [date, ic]。"""
    raise NotImplementedError("metrics.compute_ic")


def compute_group_returns(
    grouped: pl.DataFrame,
    returns: pl.DataFrame,
    num_groups: int,
) -> dict[int, float]:
    """计算各分组年化收益。"""
    raise NotImplementedError("metrics.compute_group_returns")


def compute_sharpe(returns: pl.Series, freq: str = "daily") -> float:
    """夏普比率；日频年化因子 √252。"""
    raise NotImplementedError("metrics.compute_sharpe")


def compute_max_drawdown(equity_curve: pl.Series) -> float:
    """最大回撤。"""
    raise NotImplementedError("metrics.compute_max_drawdown")


def generate_charts(
    backtest_result: BacktestResult,
    output_dir: Path,
) -> list[Path]:
    """生成净值曲线、分组收益、IC 时序图，返回图片路径。"""
    raise NotImplementedError("metrics.generate_charts")
