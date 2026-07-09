"""图表生成工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_equity_curve_chart(
    equity_data: Any,
    output_path: Path,
    title: str = "Equity Curve",
) -> Path:
    """将净值曲线保存为 PNG/HTML。"""
    raise NotImplementedError("utils.plotting.save_equity_curve_chart")


def save_group_returns_chart(
    group_returns: dict[int, float],
    output_path: Path,
    title: str = "Group Returns",
) -> Path:
    """分组年化收益柱状图。"""
    raise NotImplementedError("utils.plotting.save_group_returns_chart")


def save_ic_timeseries_chart(
    ic_series: Any,
    output_path: Path,
    title: str = "IC Time Series",
) -> Path:
    """IC 时序图。"""
    raise NotImplementedError("utils.plotting.save_ic_timeseries_chart")
