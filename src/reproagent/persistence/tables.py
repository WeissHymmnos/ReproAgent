"""SQLModel 表类（与领域模型分离）。"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class ReportTable(SQLModel, table=True):
    __tablename__ = "reports"

    id: str = Field(primary_key=True)
    file_hash: str = Field(index=True)
    file_path: str
    title: str | None = None
    broker: str | None = None
    report_date: str | None = None
    page_count: int
    validation_status: str
    ingested_at: str


class FactorLibraryTable(SQLModel, table=True):
    __tablename__ = "factor_library"

    id: str = Field(primary_key=True)
    factor_json: str  # 序列化 FactorDefinition
    report_id: str = Field(foreign_key="reports.id", index=True)
    config_id: str
    backtest_result_id: str
    deviation_passed: bool
    status: str
    version: str
    dedup_hash: str = Field(index=True)
    tags_json: str
    created_at: str


class ReflectionStateTable(SQLModel, table=True):
    __tablename__ = "reflection_states"

    id: str = Field(primary_key=True)
    factor_id: str = Field(index=True)
    report_id: str
    state_json: str  # 完整序列化 ReflectionState
    created_at: str
    updated_at: str


class ManualReviewQueueTable(SQLModel, table=True):
    __tablename__ = "manual_review_queue"

    id: str = Field(primary_key=True)
    report_id: str = Field(foreign_key="reports.id", index=True)
    reason: str
    status: str  # pending / approved / rejected
    created_at: str
