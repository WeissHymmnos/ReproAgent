"""研报与研报声称指标。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ResearchReport(BaseModel):
    """摄入的一篇研报。"""

    id: str  # UUID4
    file_path: Path
    file_hash: str  # PDF 字节 SHA256
    title: str | None = None
    author: str | None = None
    broker: str | None = None  # 如 "中信证券", "国泰君安"
    report_date: date | None = None
    page_count: int
    validation_status: Literal["pending", "valid", "invalid", "synthetic"] = "pending"
    validation_errors: list[str] = Field(default_factory=list)
    ingested_at: datetime  # UTC


class ReportedMetrics(BaseModel):
    """研报中声称的指标（LLM 从表格/正文提取）。"""

    ic_mean: float | None = None
    ic_ir: float | None = None
    long_short_return: float | None = None  # 年化, %
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    group_monotonicity: bool | None = None
    source_pages: list[int] = Field(default_factory=list)
