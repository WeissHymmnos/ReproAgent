"""Vision LLM + Pydantic schema → ParsedFactorSpec[]。"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec
from reproagent.models.report import ReportedMetrics, ResearchReport
from reproagent.parser.prompts import EXTRACTION_PROMPT
from reproagent.settings import Settings

logger = logging.getLogger(__name__)


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

    def _get_mock_spec(self) -> ParsedFactorSpec:
        return ParsedFactorSpec(
            id="mock-factor-001",
            factor_name="mock_momentum",
            factor_name_cn="模拟动量因子",
            description="A mock momentum factor for testing.",
            formula="close / Ref(close, 20) - 1",
            input_fields=[
                FactorInputField(
                    name="close",
                    report_name="收盘价",
                    data_type="price",
                    description="Daily close price",
                    frequency="daily",
                )
            ],
            computation_steps=["Calculate 20-day return using close price."],
            rebalance_frequency="monthly",
            universe="全A股",
            lookback_window=20,
            extraction_confidence=0.5,
            reported_metrics=ReportedMetrics(
                ic_mean=0.05,
                ic_ir=0.5,
                long_short_return=0.15,
                sharpe_ratio=1.0,
                max_drawdown=0.1,
                group_monotonicity=True,
            ),
        )

    def extract(self, report: ResearchReport, markdown: str) -> list[ParsedFactorSpec]:
        """将研报 Markdown 发给 LLM，用 Pydantic schema 约束输出。"""
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            logger.info("No LLM API key provided, using mock extraction.")
            return [self._get_mock_spec()]

        try:
            import instructor
            from anthropic import Anthropic
            from openai import OpenAI

            prompt = EXTRACTION_PROMPT.render(markdown=markdown)
            
            if self.settings.llm_provider == "openai":
                client = instructor.from_openai(OpenAI(api_key=api_key))
                envelope = client.chat.completions.create(
                    model=self.settings.llm_model,
                    response_model=FactorExtractionEnvelope,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.settings.llm_temperature,
                    seed=self.settings.llm_seed,
                )
            else:
                client = instructor.from_anthropic(Anthropic(api_key=api_key))
                envelope = client.messages.create(
                    model=self.settings.llm_model,
                    response_model=FactorExtractionEnvelope,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.settings.llm_temperature,
                )
            return envelope.factors
        except Exception as e:
            logger.warning(f"Real LLM extraction failed: {e}. Falling back to mock.")
            return [self._get_mock_spec()]

    def revise(
        self,
        prompt: str,
        original_spec: ParsedFactorSpec,
    ) -> ParsedFactorSpec:
        """反思循环中，给定偏差历史，生成修订版 spec。"""
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            logger.info("No LLM API key provided, using mock revision.")
            revised = original_spec.model_copy(deep=True)
            revised.formula = f"({revised.formula}) * 1.0"
            return revised

        try:
            import instructor
            from anthropic import Anthropic
            from openai import OpenAI

            if self.settings.llm_provider == "openai":
                client = instructor.from_openai(OpenAI(api_key=api_key))
                revised = client.chat.completions.create(
                    model=self.settings.llm_model,
                    response_model=ParsedFactorSpec,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.settings.llm_temperature,
                    seed=self.settings.llm_seed,
                )
            else:
                client = instructor.from_anthropic(Anthropic(api_key=api_key))
                revised = client.messages.create(
                    model=self.settings.llm_model,
                    response_model=ParsedFactorSpec,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.settings.llm_temperature,
                )
            return revised
        except Exception as e:
            logger.warning(f"Real LLM revision failed: {e}. Falling back to mock.")
            revised = original_spec.model_copy(deep=True)
            revised.formula = f"({revised.formula}) * 1.0"
            return revised
