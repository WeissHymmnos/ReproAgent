"""反思循环状态。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from reproagent.models.deviation import DeviationReport
from reproagent.models.replication import ReplicationConfig


class ReflectionStep(BaseModel):
    """反思循环中的一次迭代。"""

    id: str
    state_id: str
    iteration: int  # 0-indexed
    prompt: str
    response: str
    revised_config: ReplicationConfig
    deviation_report: DeviationReport | None = None
    created_at: datetime


class ReflectionState(BaseModel):
    """反思循环的完整状态，持久化以支持崩溃恢复。"""

    id: str
    factor_id: str
    report_id: str
    original_config: ReplicationConfig
    max_iterations: int = 3
    current_iteration: int = 0
    status: Literal["in_progress", "converged", "exhausted", "escalated"] = "in_progress"
    steps: list[ReflectionStep] = Field(default_factory=list)
    best_deviation_score: float | None = None
    best_step_id: str | None = None
    created_at: datetime
    updated_at: datetime
