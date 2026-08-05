"""ParsedFactorSpec[] → ReplicationConfig → 导出 config.yaml。"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import yaml

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings


class ConfigBuilder:
    """组装 ReplicationConfig 并导出 YAML。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_config(
        self,
        specs: list[ParsedFactorSpec],
        report: ResearchReport,
    ) -> ReplicationConfig:
        """组装 ReplicationConfig；副作用导出 config.yaml。"""
        config = ReplicationConfig(
            id=uuid.uuid4().hex,
            report_id=report.id,
            factor_specs=specs,
            engine=self.settings.default_engine,
            data_source=self.settings.data_source,
            backtest_params=BacktestParams(
                start_date=date(2018, 1, 1),
                end_date=date(2024, 12, 31),
            ),
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
