"""ReportParser Protocol。"""

from __future__ import annotations

from typing import Protocol

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.models.report import ResearchReport


class ReportParserProtocol(Protocol):
    def parse(self, report: ResearchReport) -> list[ParsedFactorSpec]:
        """全流程：布局提取 → LLM 结构化提取 → schema 校验。

        每篇研报一个因子返回一个 spec。
        校验失败重试 1 次后仍失败 → 抛 SchemaValidationError。
        """
        ...

    def build_config(
        self,
        specs: list[ParsedFactorSpec],
        report: ResearchReport,
    ) -> ReplicationConfig:
        """将 specs + 回测参数组装为 ReplicationConfig。

        副作用：导出 config.yaml 到文件系统。
        """
        ...
