"""LLM 提取的原始因子规格。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reproagent.models.report import ReportedMetrics


class FactorInputField(BaseModel):
    """因子的一个输入字段。"""

    name: str  # 映射后规范化名, 如 "turnover_rate"
    report_name: str  # 研报原文术语, 如 "换手率"
    data_type: Literal["price", "volume", "fundamental", "macro", "derived"]
    description: str = ""
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "annual"] = "daily"


class DataDictMapping(BaseModel):
    """研报术语 → 规范化数据字典映射。"""

    report_term: str
    canonical_term: str
    confidence: float  # 0.0–1.0
    tag: Literal["OK", "WARN"]  # confidence ≥ 0.8 → OK
    note: str | None = None


class ParsedFactorSpec(BaseModel):
    """LLM 从研报中提取的一个因子的原始结构化定义。"""

    id: str
    factor_name: str
    factor_name_cn: str
    description: str
    formula: str  # LaTeX 或结构化伪代码
    input_fields: list[FactorInputField]
    computation_steps: list[str]
    rebalance_frequency: Literal["daily", "weekly", "monthly", "quarterly"] = "monthly"
    universe: str = "全A股"
    lookback_window: int | None = None
    data_dict_mappings: list[DataDictMapping] = Field(default_factory=list)
    extraction_confidence: float  # 0.0–1.0
    source_pages: list[int] = Field(default_factory=list)
    reported_metrics: ReportedMetrics | None = None
