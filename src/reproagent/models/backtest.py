"""回测结果。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class BacktestResult(BaseModel):
    """一次回测的完整结果。"""

    id: str
    config_id: str
    factor_id: str
    engine: str
    start_date: date
    end_date: date
    group_annualized_returns: dict[int, float] = Field(default_factory=dict)
    ic_mean: float
    ic_ir: float
    long_short_annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    turnover: float
    factor_values_path: Path  # parquet: date, asset, factor_value
    equity_curve_path: Path  # parquet: date, group_1..N, long_short
    computed_at: datetime
