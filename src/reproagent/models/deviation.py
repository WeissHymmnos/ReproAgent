"""偏差分析与容忍配置。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RootCause(StrEnum):
    """偏差根因分类。"""

    DATA_MISMATCH = "data_mismatch"
    FORMULA_ERROR = "formula_error"
    PARAMETER_ERROR = "parameter_error"
    UNIVERSE_MISMATCH = "universe_mismatch"
    LOOKAHEAD_BIAS = "lookahead_bias"
    UNKNOWN = "unknown"


class ToleranceConfig(BaseModel):
    """核心指标容忍区间（业界标准）。"""

    ic_mean_abs: float = 0.03
    ic_ir_abs: float = 0.2
    long_short_return_rel: float = 0.15
    sharpe_abs: float = 0.3
    max_drawdown_abs: float = 0.05


class DeviationReport(BaseModel):
    """偏差分析结果。"""

    id: str
    comparison_id: str
    factor_id: str
    passed: bool
    metric_deviations: dict[str, float] = Field(default_factory=dict)
    tolerances: ToleranceConfig
    root_cause: RootCause = RootCause.UNKNOWN
    root_cause_detail: str = ""
    recommend_reflect: bool = False
    reflection_state_id: str | None = None
