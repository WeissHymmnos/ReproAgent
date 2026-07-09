"""Vision LLM + Pydantic schema → ParsedFactorSpec[]。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings


class FactorExtractionEnvelope(BaseModel):
    """LLM 输出信封：一篇研报中所有因子。"""

    factors: list[ParsedFactorSpec] = Field(description="研报中识别到的所有因子")
    report_title: str | None = None
    broker: str | None = None
    report_date: str | None = None
    extraction_confidence: float = Field(description="整体提取置信度 0-1")


class LLMExtractor:
    """结构化提取与反思修订。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, report: ResearchReport, markdown: str) -> list[ParsedFactorSpec]:
        """将研报 Markdown 发给 LLM，用 Pydantic schema 约束输出。"""
        raise NotImplementedError("LLMExtractor.extract")

    def revise(
        self,
        prompt: str,
        original_spec: ParsedFactorSpec,
    ) -> ParsedFactorSpec:
        """反思循环中，给定偏差历史，生成修订版 spec。"""
        raise NotImplementedError("LLMExtractor.revise")
