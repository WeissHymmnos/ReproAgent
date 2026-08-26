"""复现配置与回测参数。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from reproagent.models.factor_spec import ParsedFactorSpec


class BacktestParams(BaseModel):
    """回测参数。"""

    start_date: date
    end_date: date
    initial_capital: float = 1_000_000.0
    benchmark: str = "000300.SH"
    rebalance_frequency: Literal["daily", "weekly", "monthly", "quarterly"] = "monthly"
    num_groups: int = 5
    transaction_cost_bps: float = 3.0
    slippage_bps: float = 0.0
    delay: int = 1
    decay: int = 0
    neutralization: Literal["none", "market", "industry", "subindustry"] = "none"
    truncation: float | None = None
    limit_no_fill: bool = True

    mode: Literal["factor", "strategy"] = "factor"
    strategy_mode: Literal["cross_sectional", "time_series"] = "cross_sectional"
    direction: Literal["long_only", "long_short", "long_flat"] = "long_short"
    selection_rule: Literal["top_n", "bottom_n", "top_bottom_n", "threshold"] = "top_bottom_n"
    top_n: int | None = None
    bottom_n: int | None = None
    long_threshold: float | None = None
    short_threshold: float | None = None
    exit_threshold: float | None = None
    max_weight_per_position: float | None = None
    max_positions: int | None = None
    min_holding_days: int = 1


class ReplicationConfig(BaseModel):
    """一次复现的完整配置，可导出为 config.yaml。"""

    id: str
    report_id: str  # FK → ResearchReport.id
    factor_specs: list[ParsedFactorSpec]
    engine: Literal["polars", "rqalpha"] = "polars"
    data_source: Literal["ricequant", "qlib", "local", "tushare"] = "local"
    backtest_params: BacktestParams
    parser_version: str  # 如 "marker-1.0.0"
    extraction_model_id: str  # 如 "claude-sonnet-4-5"
    config_version: str = "1.0"
    created_at: datetime
