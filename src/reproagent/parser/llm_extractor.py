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
        """将研报 Markdown 发给 LLM，用 Pydantic schema 约束输出。
        
        如果模型支持视觉（如 gpt-4o 或 claude-3-5-sonnet），将附加 PDF 的前几页截图。
        """
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            logger.info("No LLM API key provided, using mock extraction.")
            return [self._get_mock_spec()]

        try:
            import instructor
            from anthropic import Anthropic
            from openai import OpenAI
            from reproagent.utils.pdf import pdf_pages_to_base64

            prompt = EXTRACTION_PROMPT.render(markdown=markdown)
            
            # 尝试提取前几页作为图像，供 Vision 模型使用
            encoded_pages = []
            if "vision" in self.settings.llm_model.lower() or "gpt-4o" in self.settings.llm_model.lower() or "claude-3-5-sonnet" in self.settings.llm_model.lower():
                encoded_pages = pdf_pages_to_base64(report.file_path, max_pages=5)
            
            if self.settings.llm_provider == "openai":
                client = instructor.from_openai(OpenAI(
                    api_key=api_key,
                    base_url=self.settings.llm_base_url
                ))
                
                content = [{"type": "text", "text": prompt}]
                for encoded_page in encoded_pages:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded_page}"}
                    })
                    
                envelope = client.chat.completions.create(
                    model=self.settings.llm_model,
                    response_model=FactorExtractionEnvelope,
                    messages=[{"role": "user", "content": content}],
                    temperature=self.settings.llm_temperature,
                    seed=self.settings.llm_seed,
                )
            else:
                client = instructor.from_anthropic(Anthropic(api_key=api_key))
                
                content = [{"type": "text", "text": prompt}]
                for encoded_page in encoded_pages:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": encoded_page
                        }
                    })
                
                envelope = client.messages.create(
                    model=self.settings.llm_model,
                    response_model=FactorExtractionEnvelope,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": content}],
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
                client = instructor.from_openai(OpenAI(
                    api_key=api_key,
                    base_url=self.settings.llm_base_url
                ))
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
