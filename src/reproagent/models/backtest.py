"""回测结果。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class BacktestResult(BaseModel):
    """一次回测的完整结果（含反过拟合检验）。"""

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
    dsr: float | None = None  # Deflated Sharpe Ratio
    dsr_pvalue: float | None = None
    pbo: float | None = None  # Probability of Backtest Overfitting
    min_btl: int | None = None  # Minimum Backtest Length
    sharpe_ci_lower: float | None = None
    sharpe_ci_upper: float | None = None
    walk_forward_ic_oos: float | None = None  # 样本外 IC 均值
    regime_ics: dict[str, float] = Field(default_factory=dict)  # 分市场环境 IC
    placebo_pvalue: float | None = None  # 安慰剂检验 p 值
    alpha_decay: dict[int, float] = Field(default_factory=dict)  # {lag_days: mean_rank_ic}
    monotonicity: float | None = None  # 分组收益单调性 (Kendall tau)
    half_life: float | None = None  # IC 半衰期（天）
