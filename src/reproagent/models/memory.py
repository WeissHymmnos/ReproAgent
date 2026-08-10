"""研究记忆领域模型（XAlpha 启发：report knowledge + discovery feedback）。

Phase 0：仅 schema；pipeline 不强制读写。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MechanismFamily(StrEnum):
    """B-layer 机制族（可扩展）。"""

    MOMENTUM = "momentum"
    REVERSAL = "reversal"
    VALUE = "value"
    GROWTH = "growth"
    QUALITY = "quality"
    SIZE = "size"
    VOLATILITY = "volatility"
    LIQUIDITY = "liquidity"
    PRICE_VOLUME = "price_volume"
    MACRO = "macro"
    TECHNICAL = "technical"
    OTHER = "other"


class EligibilityDecision(StrEnum):
    """A-layer：当前数据契约下是否可进入复现流水线。"""

    KEEP = "KEEP"
    DROP = "DROP"


class FeedbackKind(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"


class FeedbackSource(StrEnum):
    """反馈来源；mock 默认不参与 prod 路由。"""

    REAL = "real"
    MOCK = "mock"
    HUMAN = "human"


class ReportKnowledgeAtom(BaseModel):
    """研报片段吸收结果（RMA-lite）。"""

    id: str
    report_id: str
    chunk_text: str = ""
    source_pages: list[int] = Field(default_factory=list)
    a_decision: EligibilityDecision = EligibilityDecision.KEEP
    a_reason: str = ""
    mechanism_family: MechanismFamily | None = None
    research_path: str = ""
    archetype_id: str | None = None
    factor_spec_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ResearchArchetype(BaseModel):
    """C-layer：可行动研究线索（不是因子公式）。"""

    id: str
    family: MechanismFamily
    role: str
    report_grounded_paths: list[str] = Field(default_factory=list)
    source_report_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class FeedbackRecord(BaseModel):
    """发现反馈：机制级 GOOD/BAD。"""

    id: str
    kind: FeedbackKind
    report_id: str | None = None
    factor_name: str | None = None
    factor_id: str | None = None
    mechanism_family: MechanismFamily | None = None
    archetype_id: str | None = None
    failure_type: str | None = None
    root_cause: str | None = None
    avoid_rule: str | None = None
    repair_hint: str | None = None
    principle: str | None = None
    metrics_summary: dict[str, Any] = Field(default_factory=dict)
    source_run_id: str | None = None
    source: FeedbackSource = FeedbackSource.REAL
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class MemoryWriteEvent(BaseModel):
    """记忆写入审计（可选）。"""

    id: str
    event_type: Literal[
        "knowledge",
        "archetype",
        "feedback_good",
        "feedback_bad",
        "review_payload",
    ]
    entity_id: str
    report_id: str | None = None
    factor_name: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class FeedbackQuery(BaseModel):
    """反馈检索条件（Phase 2+）。"""

    kind: FeedbackKind | None = None
    mechanism_family: MechanismFamily | None = None
    factor_name: str | None = None
    root_cause: str | None = None
    failure_type: str | None = None
    include_mock: bool = False
    limit: int = 5
