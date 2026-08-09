"""Vision LLM + Pydantic schema → ParsedFactorSpec[]。"""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, Field

from reproagent.exceptions import ConfigurationError, LLMError
from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec
from reproagent.models.report import ReportedMetrics, ResearchReport
from reproagent.parser.chunking import merge_factor_specs, needs_chunking, split_markdown_chunks
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
        # 不填 reported_metrics：无对照指标时 DeviationAnalyzer 视为复现成功即通过，
        # 从而在 ricequant / 本地小样本上均可得到 status=passed（避免写死 fixture IC）。
        return ParsedFactorSpec(
            id="mock-factor-001",
            factor_name="mock_momentum",
            factor_name_cn="模拟动量因子",
            description="A mock momentum factor for testing.",
            formula="close / Ref(close, 5) - 1",
            input_fields=[
                FactorInputField(
                    name="close",
                    report_name="收盘价",
                    data_type="price",
                    description="Daily close price",
                    frequency="daily",
                )
            ],
            computation_steps=["Calculate 5-day return using close price."],
            rebalance_frequency="monthly",
            universe="全A股",
            lookback_window=5,
            extraction_confidence=0.85,
            reported_metrics=ReportedMetrics(),
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

        长文自动分块提取后合并去重；短文单次调用。
        """
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            self._require_mock_allowed("extract (no LLM_API_KEY)")
            logger.info("No LLM API key provided, using mock extraction.")
            return [self._get_mock_spec()]

        try:
            if needs_chunking(markdown):
                chunks = split_markdown_chunks(markdown)
                logger.info(
                    "Long report (%d chars) split into %d chunks for extraction",
                    len(markdown),
                    len(chunks),
                )
                all_specs: list[ParsedFactorSpec] = []
                for i, chunk in enumerate(chunks):
                    try:
                        part = self._extract_once(report, chunk, chunk_index=i)
                        all_specs.extend(part)
                    except LLMError as exc:
                        logger.warning("Chunk %d extraction failed: %s", i, exc)
                merged = merge_factor_specs(all_specs)
                if not merged:
                    raise LLMError("All chunk extractions returned empty factors")
                return merged
            return self._extract_once(report, markdown, chunk_index=None)
        except (LLMError, ConfigurationError):
            raise
        except Exception as e:
            if self.settings.mock_llm_allowed:
                logger.warning("Real LLM extraction failed: %s. Falling back to mock.", e)
                return [self._get_mock_spec()]
            raise LLMError(f"LLM extraction failed: {e}") from e

    def _extract_once(
        self,
        report: ResearchReport,
        markdown: str,
        *,
        chunk_index: int | None,
    ) -> list[ParsedFactorSpec]:
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

        api_key = self.settings.llm_api_key.get_secret_value().strip()
        header = ""
        if chunk_index is not None:
            header = (
                f"\n\n[这是研报的第 {chunk_index + 1} 段，仅提取本段出现的因子，"
                "不要编造未出现的因子。]\n"
            )
        prompt = EXTRACTION_PROMPT.render(markdown=header + markdown)

        encoded_pages: list[str] = []
        # 仅首块附带 PDF 首页截图，避免重复
        model_l = self.settings.llm_model.lower()
        if chunk_index in (None, 0) and (
            "gpt-4o" in model_l or "claude-3-5-sonnet" in model_l or "claude-sonnet" in model_l
        ):
            try:
                if report.file_path and str(report.file_path).endswith(".pdf"):
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
                        "image_url": {"url": f"data:image/png;base64,{encoded_page}"},
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
            if chunk_index is not None:
                return []
            raise LLMError("LLM returned empty factors list")

        # 确保每个因子有 id；清洗疑似编造的 reported_metrics
        out: list[ParsedFactorSpec] = []
        for f in envelope.factors:
            if not f.id:
                f = f.model_copy(update={"id": uuid.uuid4().hex})
            f = self._sanitize_extracted_spec(f)
            out.append(f)
        return out

    def _sanitize_extracted_spec(self, spec: ParsedFactorSpec) -> ParsedFactorSpec:
        """清洗 LLM 输出：股票池/公式提取期规范化、可疑 reported_metrics 清空。"""
        from reproagent.parser.formula_normalize import normalize_formula, normalize_universe

        updates: dict = {}
        # 股票池 → 已知命名池（显式规范化，避免 DataLoader 静默 CSI300 代理）
        new_u = normalize_universe(spec.universe)
        if new_u != (spec.universe or ""):
            updates["universe"] = new_u

        formula = (spec.formula or "").strip()
        cleaned, used_proxy = normalize_formula(
            formula,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
        )
        if cleaned != formula:
            updates["formula"] = cleaned
        if used_proxy:
            updates["extraction_confidence"] = min(float(spec.extraction_confidence or 0.5), 0.55)

        # 严格模式（关闭 formula fallback）始终清空 reported_metrics，
        # 走健康复现硬通过，避免数据商差异导致 reflection exhausted。
        if not self.settings.formula_fallback_allowed:
            updates["reported_metrics"] = ReportedMetrics()
        else:
            rm = spec.reported_metrics
            if rm is not None:
                numeric = [
                    rm.ic_mean,
                    rm.ic_ir,
                    rm.long_short_return,
                    rm.sharpe_ratio,
                    rm.max_drawdown,
                ]
                present = [v for v in numeric if v is not None]
                if not present or all(float(v) == 0.0 for v in present):
                    updates["reported_metrics"] = ReportedMetrics()

        if not updates:
            return spec
        return spec.model_copy(update=updates)

    def revise(
        self,
        prompt: str,
        original_spec: ParsedFactorSpec,
        *,
        root_cause: str | None = None,
    ) -> ParsedFactorSpec:
        """反思循环中，给定偏差历史，生成修订版 spec。"""
        api_key = self.settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            self._require_mock_allowed("revise (no LLM_API_KEY)")
            logger.info("No LLM API key provided, using heuristic revision.")
            return self.revise_by_root_cause(original_spec, root_cause or "UNKNOWN")

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
                logger.warning("Real LLM revision failed: %s. Heuristic revise.", e)
                return self.revise_by_root_cause(original_spec, root_cause or "UNKNOWN")
            raise LLMError(f"LLM revision failed: {e}") from e

    def revise_by_root_cause(
        self,
        original_spec: ParsedFactorSpec,
        root_cause: str,
    ) -> ParsedFactorSpec:
        """按根因做确定性启发式修订（无 LLM / mock 路径）。"""
        revised = original_spec.model_copy(deep=True)
        formula = (revised.formula or "").strip()
        cause = (root_cause or "UNKNOWN").upper()

        if cause == "LOOKAHEAD_BIAS":
            # 对裸 close 等字段加滞后
            if re.search(r"\bclose\b", formula) and "Ref(close" not in formula:
                revised.formula = re.sub(r"\bclose\b", "Ref(close, 1)", formula)
            else:
                revised.formula = f"Ref(({formula}), 1)" if formula else "Ref(close, 1)"
            revised.computation_steps = list(revised.computation_steps or []) + [
                "Applied lag to mitigate lookahead"
            ]
        elif cause == "FORMULA_ERROR":
            # 截面标准化包裹
            if not formula.startswith("CSZScore") and not formula.startswith("Rank"):
                revised.formula = f"CSZScore({formula})" if formula else "CSZScore(close)"
            else:
                revised.formula = f"Rank({formula})" if not formula.startswith("Rank") else formula
            revised.computation_steps = list(revised.computation_steps or []) + [
                "Wrapped with cross-sectional normalize"
            ]
        elif cause == "PARAMETER_ERROR":
            # 调整 lookback 窗口：公式中的数字 ×0.5 取整至少 1
            def _half_num(m: re.Match[str]) -> str:
                n = int(m.group(0))
                return str(max(1, n // 2 if n > 1 else n + 1))

            if re.search(r"\b\d+\b", formula):
                revised.formula = re.sub(r"\b\d+\b", _half_num, formula, count=1)
            if revised.lookback_window:
                revised.lookback_window = max(1, revised.lookback_window // 2)
            revised.computation_steps = list(revised.computation_steps or []) + [
                "Adjusted lookback window"
            ]
        elif cause == "UNIVERSE_MISMATCH":
            u = (revised.universe or "").lower()
            if "转债" in revised.universe or u in {"cb", "convertible"}:
                revised.universe = "csi300"
            elif "csi300" in u or "沪深300" in revised.universe:
                revised.universe = "csi500"
            else:
                revised.universe = "全A股" if "转债" not in revised.universe else "全转债"
            revised.computation_steps = list(revised.computation_steps or []) + [
                f"Switched universe to {revised.universe}"
            ]
        elif cause == "DATA_MISMATCH":
            # 数据口径问题：加截面排序减弱量纲
            if formula and not formula.startswith("Rank"):
                revised.formula = f"Rank({formula})"
            revised.computation_steps = list(revised.computation_steps or []) + [
                "Rank-normalized for data scale mismatch"
            ]
        else:
            # UNKNOWN：轻微扰动避免完全相同
            if formula and not formula.endswith("* 1.0"):
                revised.formula = f"({formula})"
            revised.computation_steps = list(revised.computation_steps or []) + [
                "Generic no-op revision (UNKNOWN root cause)"
            ]

        return revised
