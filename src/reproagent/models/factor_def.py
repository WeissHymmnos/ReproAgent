"""规范化后的可计算因子定义。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FactorDefinition(BaseModel):
    """规范化、可计算的因子定义。"""

    id: str
    spec_id: str  # FK → ParsedFactorSpec.id
    name: str
    name_cn: str
    style: Literal[
        "value",
        "growth",
        "momentum",
        "quality",
        "size",
        "volatility",
        "liquidity",
        "macro",
        "technical",
        "other",
    ]
    formula: str
    input_fields: list[str]  # 仅规范化名
    computation_code: str | None = None  # 生成的 Polars 表达式字符串
    universe: str
    rebalance_frequency: str
    version: str = "0.1.0"  # semver
    lookahead_risk: bool = False  # 是否检测到未来函数风险
    data_guard_applied: bool = False  # 是否应用了数据口径守卫筛查
    adjustment_type: str = "forward"  # 复权类型: forward / backward / none
