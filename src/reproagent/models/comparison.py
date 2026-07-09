"""复现值 vs 研报声称值对比。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from reproagent.models.backtest import BacktestResult
from reproagent.models.report import ReportedMetrics


class ComparisonReport(BaseModel):
    """复现值 vs 研报声称值的对比报告。"""

    id: str
    factor_id: str
    reproduced: BacktestResult
    reported: ReportedMetrics
    metric_deltas: dict[str, float] = Field(default_factory=dict)
    # 复现值 - 研报值, e.g. {"ic_mean": 0.03, "sharpe": 0.5}
