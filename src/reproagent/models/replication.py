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


class ReplicationConfig(BaseModel):
    """一次复现的完整配置，可导出为 config.yaml。"""

    id: str
    report_id: str  # FK → ResearchReport.id
    factor_specs: list[ParsedFactorSpec]
    engine: Literal["polars", "rqalpha"] = "polars"
    data_source: Literal["ricequant", "tushare", "local"] = "ricequant"
    backtest_params: BacktestParams
    parser_version: str  # 如 "marker-1.0.0"
    extraction_model_id: str  # 如 "claude-sonnet-4-5"
    config_version: str = "1.0"
    created_at: datetime
