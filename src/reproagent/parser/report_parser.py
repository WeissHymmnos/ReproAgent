"""ReportParser 编排：布局 → LLM → 校验 → 配置。"""

from __future__ import annotations

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.models.report import ResearchReport
from reproagent.parser.config_builder import ConfigBuilder
from reproagent.parser.layout_extractor import LayoutExtractor
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.parser.schema_validator import SchemaValidator
from reproagent.settings import Settings


class ReportParser:
    """实现 ReportParserProtocol 的薄编排器。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.layout_extractor = LayoutExtractor(backend=settings.parser_backend)
        self.llm_extractor = LLMExtractor(settings)
        self.schema_validator = SchemaValidator()
        self.config_builder = ConfigBuilder(settings)

    def parse(self, report: ResearchReport) -> list[ParsedFactorSpec]:
        """布局提取 → LLM 结构化提取 → schema 校验。"""
        raise NotImplementedError("ReportParser.parse")

    def build_config(
        self,
        specs: list[ParsedFactorSpec],
        report: ResearchReport,
    ) -> ReplicationConfig:
        """委托 ConfigBuilder。"""
        return self.config_builder.build_config(specs, report)
