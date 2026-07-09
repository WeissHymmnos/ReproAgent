"""ParsedFactorSpec[] → ReplicationConfig → 导出 config.yaml。"""

from __future__ import annotations

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
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
        raise NotImplementedError("ConfigBuilder.build_config")
