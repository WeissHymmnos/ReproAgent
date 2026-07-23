"""Vision LLM + Pydantic schema → ParsedFactorSpec[]。"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from reproagent.exceptions import ConfigurationError, LLMError
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

    def _require_mock_allowed(self, context: str) -> None:
        if not self.settings.mock_llm_allowed:
            raise LLMError(
                f"{context}: mock LLM is disabled "
                f"(app_env={self.settings.app_env!r}, allow_mock_llm="
                f"{self.settings.allow_mock_llm!r}). "
                "Set LLM_API_KEY or use APP_ENV=dev / ALLOW_MOCK_LLM=true for offline."
            )

    def extract(self, report: ResearchReport, markdown: str) -> list[ParsedFactorSpec]:
        """将研报 Markdown 发给 LLM，用 Pydantic schema 约束输出。

        如果模型支持视觉（如 gpt-4o 或 claude-3-5-sonnet），将附加 PDF 的前几页截图。
        """
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            self._require_mock_allowed("extract (no LLM_API_KEY)")
            logger.info("No LLM API key provided, using mock extraction.")
            return [self._get_mock_spec()]

        try:
            try:
                import instructor
            except ImportError as e:
                raise ConfigurationError(
                    "instructor is required for real LLM extraction. "
                    "Install with: uv sync --extra instructor"
                ) from e
            from anthropic import Anthropic
            from openai import OpenAI

            from reproagent.utils.pdf import pdf_pages_to_base64

            prompt = EXTRACTION_PROMPT.render(markdown=markdown)

            encoded_pages: list[str] = []
            model_l = self.settings.llm_model.lower()
            if "gpt-4o" in model_l or "claude-3-5-sonnet" in model_l or "claude-sonnet" in model_l:
                try:
                    encoded_pages = pdf_pages_to_base64(report.file_path, max_pages=5)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("PDF page render for vision failed: %s", exc)

            if self.settings.llm_provider == "openai":
                client = instructor.from_openai(
                    OpenAI(api_key=api_key, base_url=self.settings.llm_base_url)
                )

                content: list[dict] = [{"type": "text", "text": prompt}]
                for encoded_page in encoded_pages:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encoded_page}"
                            },
                        }
                    )

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
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded_page,
                            },
                        }
                    )

                envelope = client.messages.create(
                    model=self.settings.llm_model,
                    response_model=FactorExtractionEnvelope,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": content}],
                    temperature=self.settings.llm_temperature,
                )
            if not envelope.factors:
                raise LLMError("LLM returned empty factors list")
            return envelope.factors
        except (LLMError, ConfigurationError):
            raise
        except Exception as e:
            if self.settings.mock_llm_allowed:
                logger.warning(
                    "Real LLM extraction failed: %s. Falling back to mock.", e
                )
                return [self._get_mock_spec()]
            raise LLMError(f"LLM extraction failed: {e}") from e

    def revise(
        self,
        prompt: str,
        original_spec: ParsedFactorSpec,
    ) -> ParsedFactorSpec:
        """反思循环中，给定偏差历史，生成修订版 spec。"""
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            self._require_mock_allowed("revise (no LLM_API_KEY)")
            logger.info("No LLM API key provided, using mock revision.")
            revised = original_spec.model_copy(deep=True)
            revised.formula = f"({revised.formula}) * 1.0"
            return revised

        try:
            try:
                import instructor
            except ImportError as e:
                raise ConfigurationError(
                    "instructor is required for real LLM revision. "
                    "Install with: uv sync --extra instructor"
                ) from e
            from anthropic import Anthropic
            from openai import OpenAI

            if self.settings.llm_provider == "openai":
                client = instructor.from_openai(
                    OpenAI(api_key=api_key, base_url=self.settings.llm_base_url)
                )
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
        except (LLMError, ConfigurationError):
            raise
        except Exception as e:
            if self.settings.mock_llm_allowed:
                logger.warning(
                    "Real LLM revision failed: %s. Falling back to mock.", e
                )
                revised = original_spec.model_copy(deep=True)
                revised.formula = f"({revised.formula}) * 1.0"
                return revised
            raise LLMError(f"LLM revision failed: {e}") from e
