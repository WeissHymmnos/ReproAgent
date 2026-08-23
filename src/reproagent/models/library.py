"""因子库条目与过滤条件。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from reproagent.models.factor_def import FactorDefinition


class FactorLibraryEntry(BaseModel):
    """因子库中的一条记录。"""

    id: str
    factor: FactorDefinition
    report_id: str
    config_id: str
    backtest_result_id: str
    deviation_passed: bool
    status: Literal["ready", "review", "deprecated"] = "ready"
    version: str  # semver
    dedup_hash: str  # sha256(formula + sorted(input_fields))
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)


class LibraryFilter(BaseModel):
    """因子库过滤条件。"""

    style: str | None = None
    status: str | None = None
    broker: str | None = None
    tags: list[str] = Field(default_factory=list)
