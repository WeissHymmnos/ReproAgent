"""REST API 请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    expression: str
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    universe: str = "csi300"
    num_groups: int = Field(default=5, ge=2, le=20)


class BacktestResponse(BaseModel):
    job_id: str
    status: str  # "queued" | "running" | "done" | "failed"
    result: dict | None = None


class IngestResponse(BaseModel):
    report_id: str
    status: str
    factors_found: int = 0


class FactorSummary(BaseModel):
    id: str
    name: str
    style: str
    status: str
    version: str


class FactorListResponse(BaseModel):
    total: int
    factors: list[FactorSummary]


class BenchmarkResponse(BaseModel):
    report_id: str
    status: str
    factor_count: int
    annotation_notes: str = ""
