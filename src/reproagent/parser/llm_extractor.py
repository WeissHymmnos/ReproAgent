"""Vision LLM + Pydantic schema → ParsedFactorSpec[]。"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, cast

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
                    # 二次尝试：截断正文（严格模式仍禁止罐头公式注入）
                    short = markdown[:6000]
                    try:
                        merged = self._extract_once(report, short, chunk_index=None)
                    except LLMError:
                        merged = []
                return merged  # 可空 → pipeline no_factors
            specs = self._extract_once(report, markdown, chunk_index=None)
            # 开发模式才允许二次“塞示例公式”重提；严格评分路径禁止罐头注入
            if not specs and self.settings.formula_fallback_allowed:
                specs = self._extract_once(
                    report,
                    markdown[:6000]
                    + "\n\n[强制] 请至少输出 1 个因子，formula 示例: close/Ref(close,20)-1",
                    chunk_index=None,
                )
            return specs
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
        skip_strict_recovery: bool = False,
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
                messages=cast(Any, [{"role": "user", "content": content}]),
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
                messages=cast(Any, [{"role": "user", "content": content}]),
                temperature=self.settings.llm_temperature,
            )

        if not envelope.factors:
            # 诚实：空提取 → []，由 pipeline 报 no_factors（不 raise 成 hard_fail）
            logger.warning("LLM returned empty factors list (chunk=%s)", chunk_index)
            return []

        from reproagent.parser.formula_normalize import is_executable
        from reproagent.reproducer.run_flags import mark_recovery_used

        # Stage A: LLM + 机械规范化 only。严格路径返回全部可执行非代理因子（可多因子）。
        out: list[ParsedFactorSpec] = []
        dropped_proxy: list[ParsedFactorSpec] = []
        for f in envelope.factors:
            if not f.id:
                f = f.model_copy(update={"id": uuid.uuid4().hex})
            f = self._sanitize_extracted_spec(f)
            if getattr(f, "_strict_drop", False):
                logger.warning(
                    "Dropping non-honest factor %s (proxy/universe_fallback/strict)",
                    f.factor_name,
                )
                dropped_proxy.append(f)
                continue
            if not is_executable(f.formula or ""):
                logger.warning(
                    "Dropping non-executable factor %s %r",
                    f.factor_name,
                    (f.formula or "")[:60],
                )
                continue
            out.append(f)

        # 严格模式：保留**所有** dry-run 健康因子（可多因子；≠ keep-first 只留 1 个）
        if not self.settings.formula_fallback_allowed and out and not skip_strict_recovery:
            healthy: list[ParsedFactorSpec] = []
            for cand in out:
                if self._dry_run_factor_ok(cand):
                    healthy.append(cand)
                    logger.info(
                        "Strict mode: dry-run OK keep %s formula=%r",
                        cand.factor_name,
                        (cand.formula or "")[:60],
                    )
                else:
                    logger.warning(
                        "Strict mode: dry-run drop %s formula=%r",
                        cand.factor_name,
                        (cand.formula or "")[:60],
                    )
            out = healthy

        # 严格模式：全部被丢弃时，再问一次 LLM（仅白名单约束，**无** ROE/动量罐头配方）
        if (
            not out
            and not self.settings.formula_fallback_allowed
            and not skip_strict_recovery
            and chunk_index is None
            and markdown
        ):
            out = self._strict_whitelist_reask(report, markdown)
            # re-ask 结果同样做 multi dry-run 过滤
            if out:
                healthy2 = [c for c in out if self._dry_run_factor_ok(c)]
                out = healthy2

        # Stage B: 名称域恢复级联仅在 formula_fallback_allowed（开发）时启用
        if (
            self.settings.formula_fallback_allowed
            and not skip_strict_recovery
            and not out
            and (envelope.factors or dropped_proxy)
        ):
            mark_recovery_used("dev_domain_proxy")
            candidates = dropped_proxy or list(envelope.factors or [])
            base = candidates[0] if candidates else None
            if base is not None:
                if not base.id:
                    base = base.model_copy(update={"id": uuid.uuid4().hex})
                out = self._domain_formula_as_proxy(base)
        return out

    def _strict_whitelist_reask(
        self,
        report: ResearchReport,
        markdown: str,
    ) -> list[ParsedFactorSpec]:
        """严格二次提问：不注入罐头公式，只强调白名单与可多因子。"""
        force_md = (
            markdown[:7000]
            + "\n\n[重提约束] 上一轮因子无法用引擎字段执行。"
            "请重新提取：**可输出多个**因子；每个 formula 只能使用 "
            "Rank/CSZScore/Ref/Mean/Std/Sum/Delta/EMA/Abs/Log/Sign/Sqrt/Pow/Max/Min "
            "与 open/high/low/close/volume/amount/market_cap/pe_ratio/pb_ratio/return_on_equity。"
            "时序算子必须带整数窗口（如 Std(x,20)）。"
            "无法用上述字段表达的因子请**省略**（不要用未知变量，不要用概念名顶替）。"
            "universe 仅 csi300/csi500/csi1000/全A股。"
        )
        try:
            return self._extract_once(
                report, force_md, chunk_index=None, skip_strict_recovery=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Strict whitelist re-ask failed: %s", exc)
            return []

    def _domain_formula_as_proxy(self, base: ParsedFactorSpec) -> list[ParsedFactorSpec]:
        """名称域公式 = 整式启发式代理，必须 mark formula_proxy（仅 dev recovery）。"""
        from reproagent.reproducer.run_flags import mark_formula_proxy

        for fml in self._domain_formulas(base.factor_name or "", base.factor_name_cn or ""):
            cand = base.model_copy(
                update={
                    "formula": fml,
                    "universe": "csi300",
                    "reported_metrics": ReportedMetrics(),
                    "extraction_confidence": min(
                        float(base.extraction_confidence or 0.5), 0.45
                    ),
                }
            )
            if self._dry_run_factor_ok(cand):
                mark_formula_proxy(base.factor_name or "", "domain_name_heuristic")
                logger.info(
                    "Dev recovery: domain formula as PROXY %s %r",
                    base.factor_name,
                    fml,
                )
                return [cand]
        return []

    def _domain_formulas(self, factor_name: str, factor_name_cn: str) -> list[str]:
        """按名称给出候选真实字段公式（均 is_executable；调用方须标 proxy）。"""
        blob = f"{factor_name} {factor_name_cn}".lower()
        cands: list[str] = []
        if any(k in blob for k in ("vol", "波动", "std", "方差", "idiosyncrat")):
            cands.append("-1 * CSZScore(Std(close / Ref(close, 1) - 1, 20))")
        if any(k in blob for k in ("size", "市值", "mkt", "cap", "equal", "weight", "risk")):
            cands.append("-1 * CSZScore(Log(market_cap))")
        if any(k in blob for k in ("roe", "盈利", "profit", "quality", "质量")):
            cands.append("CSZScore(return_on_equity)")
        if any(k in blob for k in ("pe", "pb", "value", "估值", "ep")):
            cands.append("-1 * CSZScore(pe_ratio)")
        if any(k in blob for k in ("turn", "换手", "volume", "成交", "liquid")):
            cands.append("-1 * CSZScore(Mean(volume, 20) / Mean(volume, 60))")
        if any(k in blob for k in ("mom", "动量", "reversal", "反转")):
            cands.append("close / Ref(close, 20) - 1")
        cands.append("close / Ref(close, 20) - 1")
        seen: set[str] = set()
        out: list[str] = []
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _dry_run_factor_ok(self, spec: ParsedFactorSpec) -> bool:
        """短窗回测：公式可算且结果健康（无代理）。"""
        from reproagent.reproducer.run_flags import get_run_flags, restore_run_flags

        flags_before = {
            "formula_fallback": bool(get_run_flags().get("formula_fallback", False)),
            "formula_proxy": bool(get_run_flags().get("formula_proxy", False)),
            "universe_fallback": bool(get_run_flags().get("universe_fallback", False)),
            "universe_fallback_reason": get_run_flags().get("universe_fallback_reason"),
            "soft_pass": bool(get_run_flags().get("soft_pass", False)),
            "proxy_factors": list(get_run_flags().get("proxy_factors") or []),
        }
        try:
            from datetime import UTC, date, datetime

            from reproagent.models.replication import BacktestParams, ReplicationConfig
            from reproagent.reproducer.data_loader import DataLoader
            from reproagent.reproducer.health import is_healthy_reproduction
            from reproagent.reproducer.reproducer import FactorReproducer

            # 与默认 full 回测窗口一致，避免 short-window dry-run 通过、full 再 fail → partial
            cfg = ReplicationConfig(
                id="dry",
                report_id="dry",
                factor_specs=[spec],
                engine="polars",
                data_source=self.settings.data_source,
                backtest_params=BacktestParams(
                    start_date=date(2018, 1, 1),
                    end_date=date(2024, 12, 31),
                ),
                parser_version=self.settings.parser_version,
                extraction_model_id=self.settings.llm_model,
                created_at=datetime.now(UTC),
            )
            loader = DataLoader(self.settings)
            rep = FactorReproducer(self.settings, loader)
            result = rep.reproduce(cfg)
            ok = bool(is_healthy_reproduction(result))
            # 若 dry-run 自身引入了 proxy，该候选不算 OK
            if get_run_flags().get("formula_proxy") and not flags_before.get("formula_proxy"):
                ok = False
            return ok
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            # universe 解析失败 → 不放行（避免 dry-run 放行后 full 因 csi1000 配额再炸）
            if any(
                k in msg
                for k in (
                    "cannot resolve",
                    "unrecognized ricequant universe",
                    "empty index components",
                )
            ):
                logger.warning("dry-run universe fail for %s: %s", spec.factor_name, exc)
                return False
            # 纯量价拉取配额/瞬时网络：公式可执行则放行（磁盘面板可兜底）
            infra = any(
                k in msg
                for k in (
                    "quota",
                    "rate limit",
                    "too many requests",
                    "timeout",
                    "temporarily",
                    "connection",
                )
            )
            if infra:
                from reproagent.parser.formula_normalize import is_executable

                if is_executable((spec.formula or "").strip()):
                    logger.warning(
                        "dry-run data-infra fail for %s, accepting executable formula: %s",
                        spec.factor_name,
                        exc,
                    )
                    return True
            logger.warning("dry-run failed for %s: %s", spec.factor_name, exc)
            return False
        finally:
            # 无论成败，dry-run 不得污染主流程 observability
            restore_run_flags(flags_before)

    def _sanitize_extracted_spec(self, spec: ParsedFactorSpec) -> ParsedFactorSpec:
        """清洗 LLM 输出：机械规范化；代理/未知池必须打标。

        严格模式：used_proxy 或 universe_fallback → _strict_drop（不静默 CSI300 冒充成功）。
        """
        from reproagent.parser.formula_normalize import normalize_all
        from reproagent.reproducer.run_flags import mark_formula_proxy, mark_universe_fallback

        allow_proxy = bool(self.settings.formula_fallback_allowed)
        nr = normalize_all(
            formula=spec.formula,
            universe=spec.universe,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
            allow_proxy=allow_proxy,
        )
        updates: dict = {
            "formula": nr.formula,
            "universe": nr.universe,
        }
        # 未知池：开发模式 remap+打标；严格模式丢弃该因子（不静默 CSI300，也不污染兄弟因子）
        if nr.universe_fallback:
            if allow_proxy:
                mark_universe_fallback(f"extract:{spec.universe!r}->{nr.universe}")
                updates["universe"] = nr.universe
            # else: 保持 nr.universe 但 _strict_drop，见下

        if nr.used_proxy and allow_proxy:
            mark_formula_proxy(spec.factor_name or "", "extract_proxy")
            updates["extraction_confidence"] = min(
                float(spec.extraction_confidence or 0.5), 0.45
            )

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

        updated = spec.model_copy(update=updates)
        # 严格：代理式或未知池 → 丢弃（禁止 remap 后无旗标 passed）
        strict_drop = bool(
            not allow_proxy and (nr.used_proxy or nr.universe_fallback)
        )
        object.__setattr__(updated, "_strict_drop", strict_drop)
        return updated

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
