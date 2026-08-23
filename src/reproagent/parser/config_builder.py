"""ParsedFactorSpec[] → ReplicationConfig → 导出 config.yaml。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Any

import yaml

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings


def apply_backtest_kwargs(
    config: ReplicationConfig,
    backtest_kwargs: dict[str, Any] | None,
) -> ReplicationConfig:
    """Overlay workstation/CLI backtest knobs onto a (possibly cached) config."""
    if not backtest_kwargs:
        return config
    merged = config.backtest_params.model_dump()
    merged.update(backtest_kwargs)
    params = BacktestParams(**merged)
    return config.model_copy(update={"backtest_params": params})


def backtest_params_token(params: BacktestParams) -> str:
    """Stable short hash so factor-mode and strategy-mode caches do not collide."""
    return hashlib.sha256(params.model_dump_json().encode("utf-8")).hexdigest()[:12]


class ConfigBuilder:
    """组装 ReplicationConfig 并导出 YAML。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_config(
        self,
        specs: list[ParsedFactorSpec],
        report: ResearchReport,
        backtest_kwargs: dict[str, Any] | None = None,
    ) -> ReplicationConfig:
        """组装 ReplicationConfig；副作用导出 config.yaml。"""
        bt_params: dict[str, Any] = {
            "start_date": date(2018, 1, 1),
            "end_date": date(2024, 12, 31),
        }
        if backtest_kwargs:
            bt_params.update(backtest_kwargs)

        config = ReplicationConfig(
            id=uuid.uuid4().hex,
            report_id=report.id,
            factor_specs=specs,
            engine=self.settings.default_engine,
            data_source=self.settings.data_source,
            backtest_params=BacktestParams(**bt_params),
            parser_version=self.settings.parser_version,
            extraction_model_id=self.settings.llm_model,
            created_at=datetime.now(UTC),
        )

        report_dir = self.settings.reports_dir / report.id
        report_dir.mkdir(parents=True, exist_ok=True)
        config_path = report_dir / "config.yaml"

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)

        return config
