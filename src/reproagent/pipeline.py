"""端到端流程编排：摄入 → 解析 → 复现 → 偏差 → 反思 → 入库。

支持一篇研报中的多个因子：逐个复现并汇总结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reproagent.settings import Settings


def _notify_catalog_library(entry: Any, backtest: Any) -> None:
    import os

    if os.environ.get("FINAINCE_CATALOG", "1") == "0":
        return
    try:
        from finaince.catalog.hooks import accept_library_entry

        from reproagent.reproducer.metrics import serialize_equity_returns
        from reproagent.reproducer.run_flags import snapshot_run_flags
    except ImportError:
        return
    extras = {
        "metrics": {
            "ic_mean": getattr(backtest, "ic_mean", None),
            "ic_ir": getattr(backtest, "ic_ir", None),
            "sharpe_ratio": getattr(backtest, "sharpe_ratio", None),
            "max_drawdown": getattr(backtest, "max_drawdown", None),
            "long_short_annual_return": getattr(backtest, "long_short_annual_return", None),
        },
        "daily_returns": serialize_equity_returns(getattr(backtest, "equity_curve_path", None)),
        "factor_values_uri": str(getattr(backtest, "factor_values_path", "") or "") or None,
        "observability": snapshot_run_flags(),
    }
    try:
        accept_library_entry(entry, extras=extras)
    except Exception:  # noqa: BLE001
        return


def _single_factor_config(config: Any, spec: Any) -> Any:
    """从多因子 config 切出仅含一个 spec 的副本。"""
    return config.model_copy(update={"factor_specs": [spec]}, deep=True)


def _process_one_factor(
    *,
    spec: Any,
    config: Any,
    report: Any,
    markdown: str,
    specs: list[Any],
    cache_key: str,
    cache_manager: Any,
    cached_data: Any,
    reproducer: Any,
    analyzer: Any,
    tolerances: Any,
    library_manager: Any,
    reflection_controller: Any,
    repository: Any,
    logger: Any,
    experience_memory: Any = None,
    memory_writer: Any = None,
    pipeline_settings: Any = None,
) -> dict[str, Any]:
    import uuid
    from datetime import UTC, datetime

    from reproagent.library.versioning import compute_dedup_hash
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.models.report import ReportedMetrics

    factor_config = _single_factor_config(config, spec)
    from reproagent.settings import get_settings as _gs

    reported = spec.reported_metrics or ReportedMetrics()
    factor_name = spec.factor_name
    input_fields = [f.name for f in (spec.input_fields or [])]

    # 置信度门控：空公式仍硬拦截；其余低置信/WARN 改为软提示并继续复现，
    # 避免仅因 extraction_confidence 偏低就跳过可计算的量价因子。
    from reproagent.parser.confidence import evaluate_confidence

    gate = evaluate_confidence(spec)
    if not gate.ok:
        hard_reasons = [r for r in gate.reasons if r.startswith("empty_formula")]
        if hard_reasons:
            reason = f"Confidence gate failed for {factor_name}: {', '.join(gate.reasons)}"
            repository.enqueue_review(report.id, reason)
            return {
                "factor_name": factor_name,
                "status": "review_enqueued",
                "reflection_status": "confidence_gate",
                "confidence": {
                    "ok": False,
                    "reasons": gate.reasons,
                    "extraction_confidence": gate.extraction_confidence,
                },
            }
        logger.warning(
            "Confidence soft-fail for %s (continuing reproduce): %s",
            factor_name,
            ", ".join(gate.reasons),
        )

    from reproagent.parser.formula_normalize import normalize_all
    from reproagent.reproducer.health import is_healthy_reproduction
    from reproagent.reproducer.run_flags import mark_formula_proxy, mark_universe_fallback

    allow_proxy = bool(_gs().formula_fallback_allowed)
    # 计算前规范化（严格模式禁止整式代理：proxy 直接 review，不冒充 passed）
    if factor_config.factor_specs:
        fs0 = factor_config.factor_specs[0]
        nr = normalize_all(
            formula=fs0.formula,
            universe=fs0.universe,
            factor_name=fs0.factor_name or "",
            factor_name_cn=fs0.factor_name_cn or "",
            allow_proxy=allow_proxy,
        )
        if nr.used_proxy:
            mark_formula_proxy(fs0.factor_name or "", "pipeline_proxy")
            if not allow_proxy:
                repository.enqueue_review(
                    report.id,
                    f"Strict mode: proxy formula rejected for {factor_name}",
                )
                return {
                    "factor_name": factor_name,
                    "status": "review_enqueued",
                    "reflection_status": "strict_proxy_rejected",
                }
        if nr.universe_fallback:
            mark_universe_fallback(f"pipeline:{fs0.universe!r}->{nr.universe}")
            if not allow_proxy:
                repository.enqueue_review(
                    report.id,
                    f"Strict mode: universe fallback rejected for {factor_name}",
                )
                return {
                    "factor_name": factor_name,
                    "status": "review_enqueued",
                    "reflection_status": "strict_universe_fallback_rejected",
                }
        factor_config = factor_config.model_copy(deep=True)
        factor_config.factor_specs[0] = fs0.model_copy(
            update={"formula": nr.formula, "universe": nr.universe}
        )

    from reproagent.reproducer.lookahead_detector import detect_lookahead

    _final_formula = (
        factor_config.factor_specs[0].formula
        if factor_config.factor_specs
        else spec.formula
    )
    lookahead_report = detect_lookahead(_final_formula or "")
    if lookahead_report.has_lookahead:
        first = (
            lookahead_report.findings[0].description
            if lookahead_report.findings
            else "future reference"
        )
        reason = f"Lookahead bias detected for {factor_name}: {first}"
        repository.enqueue_review(report.id, reason)
        logger.warning("Lookahead hard-block for %s: %s", factor_name, reason)
        return {
            "factor_name": factor_name,
            "status": "review_enqueued",
            "reflection_status": "lookahead_blocked",
            "lookahead": {
                "has_lookahead": True,
                "risk_level": lookahead_report.risk_level,
            },
        }

    from reproagent.parser.config_builder import backtest_params_token

    params_token = backtest_params_token(factor_config.backtest_params)
    cached_bt = cache_manager.get_cached_backtest(
        cache_key, factor_name, params_token=params_token
    )
    if cached_bt and is_healthy_reproduction(cached_bt):
        result = cached_bt
        logger.info("Loaded backtest result from cache for %s", factor_name)
    else:
        result = reproducer.reproduce(factor_config)
        # 严格模式：不健康不重试代理；开发模式才允许（且已打标）
        if not is_healthy_reproduction(result) and allow_proxy:
            nr2 = normalize_all(
                formula="",
                universe=factor_config.factor_specs[0].universe,
                factor_name=factor_name or "",
                factor_name_cn=getattr(spec, "factor_name_cn", "") or "",
                allow_proxy=True,
            )
            mark_formula_proxy(factor_name or "", "unhealthy_retry_proxy")
            factor_config = factor_config.model_copy(deep=True)
            factor_config.factor_specs[0] = factor_config.factor_specs[0].model_copy(
                update={"formula": nr2.formula}
            )
            result = reproducer.reproduce(factor_config)
        if cached_data is not None and is_healthy_reproduction(result):
            cache_manager.save(
                cache_key,
                markdown,
                specs,
                config,
                result,
                params_token=params_token,
            )

    deviation = analyzer.analyze(result, reported, tolerances)
    deviation.root_cause = analyzer.classify_root_cause(deviation, factor_config)

    if deviation.passed and is_healthy_reproduction(result):
        # 以回测结果健康度为准；二次 compute 仅用于入库定义，失败不撤销已健康的回测
        try:
            factor_def, _factor_vals = reproducer.compute_factor(
                factor_config, factor_config.factor_specs[0]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("compute_factor for register failed (%s); building def only", exc)
            factor_def = reproducer._build_factor_def(factor_config.factor_specs[0])
        from reproagent.reproducer.metrics import metrics_from_backtest

        entry = FactorLibraryEntry(
            id=uuid.uuid4().hex,
            factor=factor_def,
            report_id=report.id,
            config_id=factor_config.id,
            backtest_result_id=result.id,
            deviation_passed=True,
            version="1.0.0",
            dedup_hash=compute_dedup_hash(factor_def),
            created_at=datetime.now(UTC),
            metrics=metrics_from_backtest(result),
        )
        saved = library_manager.register(entry)
        _notify_catalog_library(saved, result)
        if experience_memory is not None:
            try:
                experience_memory.record_success(
                    formula=factor_config.factor_specs[0].formula,
                    input_fields=input_fields,
                    style=factor_def.style,
                    ic=float(result.ic_mean or 0.0),
                    report_id=report.id,
                )
                for m in spec.data_dict_mappings or []:
                    experience_memory.learn_term_mapping(
                        m.report_term, m.canonical_term, m.confidence
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ExperienceMemory.record_success failed: %s", exc)
        return {
            "factor_name": factor_name,
            "status": "passed",
            "factor_id": saved.id,
            "backtest_result_id": result.id,
            "formula": getattr(factor_config.factor_specs[0], "formula", None)
            if factor_config.factor_specs
            else None,
            "metrics": {
                "ic_mean": result.ic_mean,
                "ic_ir": result.ic_ir,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "long_short_annual_return": result.long_short_annual_return,
            },
        }

    settings_now = pipeline_settings or _gs()
    if settings_now.skip_mock_reflection and settings_now.mock_llm_allowed:
        reason = f"Reflection failed for {factor_name}: skipped_mock"
        queued = repository.enqueue_review(
            report.id,
            reason,
            payload={
                "reason_type": "reflection_skipped_mock",
                "factor_name": factor_name,
            },
        )
        if memory_writer is not None:
            try:
                from reproagent.models.memory import FeedbackSource

                memory_writer.write_bad(
                    report_id=report.id,
                    spec=spec,
                    factor_name=factor_name,
                    failure_type="reflection_skipped_mock",
                    root_cause="data_mismatch",
                    source=FeedbackSource.MOCK,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("MemoryWriter.write_bad failed: %s", exc)
        return {
            "factor_name": factor_name,
            "status": "review_enqueued" if queued else "skipped_mock",
            "reflection_status": "skipped_mock",
        }

    state = reflection_controller.run(factor_config, reported)
    if state.status == "converged":
        best_step = next((s for s in state.steps if s.id == state.best_step_id), None)
        if best_step and best_step.revised_config.factor_specs:
            revised_spec = best_step.revised_config.factor_specs[0]
            factor_def, _ = reproducer.compute_factor(
                best_step.revised_config,
                revised_spec,
            )
            bt_id = (
                best_step.deviation_report.comparison_id
                if best_step.deviation_report
                else uuid.uuid4().hex
            )
            from reproagent.reproducer.metrics import metrics_from_backtest

            entry = FactorLibraryEntry(
                id=uuid.uuid4().hex,
                factor=factor_def,
                report_id=report.id,
                config_id=best_step.revised_config.id,
                backtest_result_id=bt_id,
                deviation_passed=True,
                version="1.0.0",
                dedup_hash=compute_dedup_hash(factor_def),
                created_at=datetime.now(UTC),
                metrics=metrics_from_backtest(
                    getattr(best_step, "backtest_result", None) or result
                ),
            )
            saved = library_manager.register(entry)
            _notify_catalog_library(saved, getattr(best_step, "backtest_result", None) or result)
            cache_manager.save(
                cache_key,
                cached_data[0] if cached_data else markdown,
                best_step.revised_config.factor_specs,
                best_step.revised_config,
            )
            if experience_memory is not None:
                try:
                    experience_memory.record_success(
                        formula=revised_spec.formula,
                        input_fields=[f.name for f in (revised_spec.input_fields or [])],
                        style=factor_def.style,
                        ic=0.0,
                        report_id=report.id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ExperienceMemory.record_success failed: %s", exc)
            return {
                "factor_name": factor_name,
                "status": "converged",
                "factor_id": saved.id,
                "reflection_status": state.status,
            }

    # 软通过：严格模式（formula_fallback 关闭）下禁用，不计入无回退完全跑通
    from reproagent.settings import get_settings as _get_settings

    _allow_soft = bool(_get_settings().formula_fallback_allowed)
    soft = _try_soft_pass_after_reflection(
        state=state,
        result=result,
        deviation=deviation,
        factor_config=factor_config,
        spec=spec,
        report=report,
        reproducer=reproducer,
        library_manager=library_manager,
        experience_memory=experience_memory,
        logger=logger,
        allow_soft_pass=_allow_soft,
    )
    if soft is not None:
        return soft

    reason = f"Reflection failed for {factor_name}: {state.status}"
    queued = repository.enqueue_review(report.id, reason)
    if experience_memory is not None:
        try:
            failure_mode = (
                deviation.root_cause.value
                if hasattr(deviation.root_cause, "value")
                else str(deviation.root_cause)
            )
            experience_memory.record_failure(
                formula=spec.formula,
                input_fields=input_fields,
                failure_mode=failure_mode,
                deviation_values=dict(deviation.metric_deviations or {}),
                report_id=report.id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ExperienceMemory.record_failure failed: %s", exc)
    return {
        "factor_name": factor_name,
        "status": "review_enqueued" if queued else str(state.status or "exhausted"),
        "reflection_status": state.status,
    }


def _try_soft_pass_after_reflection(
    *,
    state: Any,
    result: Any,
    deviation: Any,
    factor_config: Any,
    spec: Any,
    report: Any,
    reproducer: Any,
    library_manager: Any,
    experience_memory: Any,
    logger: Any,
    allow_soft_pass: bool = True,
) -> dict[str, Any] | None:
    """当数值偏差无法对齐但复现结果健康时，登记为 passed（soft）。

    硬条件：因子值非空且非常数 + 指标非全零退化。0.0 IC 单独不算健康。
    严格模式（allow_soft_pass=False）下禁用，不计入无回退完全跑通。
    """
    import uuid
    from datetime import UTC, datetime

    from reproagent.library.versioning import compute_dedup_hash
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.reproducer.health import is_healthy_reproduction
    from reproagent.reproducer.run_flags import mark_soft_pass

    if not allow_soft_pass:
        return None

    # 优先用反思过程中最优一步的健康度，否则用首次回测
    cand = result
    cfg = factor_config
    if state is not None and getattr(state, "best_step_id", None) and getattr(state, "steps", None):
        best_step = next((s for s in state.steps if s.id == state.best_step_id), None)
        if best_step is not None and best_step.revised_config.factor_specs:
            cfg = best_step.revised_config

    if not is_healthy_reproduction(cand):
        return None

    cause = getattr(deviation, "root_cause", None)
    cause_s = str(getattr(cause, "value", None) or cause or "")
    # lookahead 硬拦截
    if cause_s == "lookahead_bias":
        return None

    try:
        use_spec = cfg.factor_specs[0] if cfg.factor_specs else spec
        factor_def, factor_vals = reproducer.compute_factor(cfg, use_spec)
        # 再次确认当前配置算出的因子值可用（避免 null-factor 假通过）
        if not is_healthy_reproduction(cand, factor_values=factor_vals):
            return None
        from reproagent.reproducer.metrics import metrics_from_backtest

        entry = FactorLibraryEntry(
            id=uuid.uuid4().hex,
            factor=factor_def,
            report_id=report.id,
            config_id=cfg.id,
            backtest_result_id=getattr(cand, "id", None) or uuid.uuid4().hex,
            deviation_passed=True,
            version="1.0.0",
            dedup_hash=compute_dedup_hash(factor_def),
            created_at=datetime.now(UTC),
            metrics=metrics_from_backtest(cand),
        )
        saved = library_manager.register(entry)
        _notify_catalog_library(saved, cand)
        if experience_memory is not None:
            try:
                experience_memory.record_success(
                    formula=use_spec.formula,
                    input_fields=[f.name for f in (use_spec.input_fields or [])],
                    style=factor_def.style,
                    ic=float(getattr(cand, "ic_mean", 0.0) or 0.0),
                    report_id=report.id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ExperienceMemory.record_success (soft) failed: %s", exc)
        mark_soft_pass()
        logger.info(
            "Soft-pass factor %s after reflection status=%s root_cause=%s",
            use_spec.factor_name,
            getattr(state, "status", None),
            cause_s,
        )
        return {
            "factor_name": use_spec.factor_name,
            "status": "soft_passed",
            "factor_id": saved.id,
            "reflection_status": f"soft_pass:{getattr(state, 'status', 'n/a')}",
            "soft_pass": True,
            "metrics": {
                "ic_mean": getattr(cand, "ic_mean", None),
                "ic_ir": getattr(cand, "ic_ir", None),
                "sharpe_ratio": getattr(cand, "sharpe_ratio", None),
                "max_drawdown": getattr(cand, "max_drawdown", None),
                "long_short_annual_return": getattr(cand, "long_short_annual_return", None),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Soft-pass failed for %s: %s", getattr(spec, "factor_name", "?"), exc)
        return None


def _aggregate_status(factor_results: list[dict[str, Any]]) -> str:
    if not factor_results:
        return "no_factors"
    statuses = {r["status"] for r in factor_results}
    success = {"passed", "converged"}
    if statuses <= success:
        return "passed"
    if statuses & success:
        return "partial"
    if "review_enqueued" in statuses:
        return "review_enqueued"
    if "soft_passed" in statuses:
        return "partial"
    return next(iter(statuses))


def _versioned_cache_key(file_hash: str, settings: Settings) -> str:
    """file_hash + 解析器 schema 版本 + 提取模型 共同决定缓存键，防陈旧重放。"""
    from reproagent.cache.cache_key import (
        PARSER_CACHE_SCHEMA_VERSION,
        compute_cache_key,
    )

    return compute_cache_key(
        file_hash,
        parser_version=PARSER_CACHE_SCHEMA_VERSION,
        extraction_model_id=f"{settings.llm_provider}:{settings.llm_model}",
    )


def _data_context(settings: Settings, config: Any) -> dict[str, Any]:
    """输出实际生效的数据源/路径/回测窗口，避免 .env 静默覆盖造成的困惑。"""
    bp = getattr(config, "backtest_params", None)
    specs = getattr(config, "factor_specs", None)
    return {
        "data_source": settings.data_source,
        "local_data_path": (
            str(settings.local_data_path) if settings.data_source == "local" else None
        ),
        "backtest_window": (
            {"start": str(bp.start_date), "end": str(bp.end_date)} if bp else None
        ),
        "universe": specs[0].universe if specs else None,
    }


def reproduce_report(
    pdf_path: Path,
    settings: Settings,
    backtest_kwargs: dict[str, Any] | None = None,
) -> dict | None:
    path = Path(pdf_path)
    if path.suffix.lower() in {".md", ".txt"}:
        return reproduce_text(
            path.read_text(encoding="utf-8", errors="replace"),
            settings,
            title=path.stem or "Markdown Input",
            backtest_kwargs=backtest_kwargs,
        )

    import logging

    from reproagent.cache.cache_manager import CacheManager
    from reproagent.deviation.analyzer import DeviationAnalyzer
    from reproagent.deviation.reflection_loop import ReflectionLoopController
    from reproagent.ingestion.uploader import upload_pdf
    from reproagent.ingestion.validator import validate_pdf
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.models.deviation import ToleranceConfig
    from reproagent.parser.report_parser import ReportParser
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.reproducer.reproducer import FactorReproducer
    from reproagent.reproducer.run_flags import begin_run_flags

    begin_run_flags()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()

    engine = get_engine(settings.db_path)
    init_db(engine)

    repository = Repository(engine)

    # 1. Ingestion
    incoming = upload_pdf(pdf_path)
    incoming = validate_pdf(incoming)
    existing = repository.get_report_by_hash(incoming.file_hash)
    if existing is not None:
        report = existing
    else:
        report = incoming
        repository.save_report(report)

    if report.validation_status == "invalid":
        if existing is None:
            repository.enqueue_review(report.id, "PDF validation failed")
        return _finalize_pipeline_result(
            overall="invalid",
            factor_results=[],
            report_id=report.id,
            source="pdf",
        )

    cache_manager = CacheManager(paths)
    cache_key = _versioned_cache_key(report.file_hash, settings)

    # 2. Parse (with cache). 严格模式跳过 parse cache，避免冻结旧版 domain/proxy 公式。
    parser = ReportParser(settings)
    cached_data = cache_manager.get_cached(cache_key)
    markdown = ""
    use_parse_cache = cached_data is not None and bool(settings.formula_fallback_allowed)
    if use_parse_cache and cached_data is not None:
        markdown, specs, config = cached_data
        from reproagent.parser.config_builder import apply_backtest_kwargs

        config = apply_backtest_kwargs(config, backtest_kwargs)
        logger.info("Loaded parsing results from cache for %s", cache_key)
    else:
        if cached_data and not settings.formula_fallback_allowed:
            logger.info(
                "Strict mode: ignoring parse cache for %s (re-extract)", cache_key
            )
        try:
            specs = parser.parse(report)
        except ValueError as exc:
            reason = f"Schema validation failed for extracted factors: {exc}"
            repository.enqueue_review(report.id, reason)
            logger.warning("parse() rejected specs for %s: %s", report.id, exc)
            return _finalize_pipeline_result(
                overall="review_enqueued",
                factor_results=[],
                report_id=report.id,
                source="pdf",
            )
        if not specs:
            repository.enqueue_review(report.id, "No factors extracted")
            return _finalize_pipeline_result(
                overall="no_factors",
                factor_results=[],
                report_id=report.id,
                source="pdf",
            )
        config = parser.build_config(specs, report, backtest_kwargs=backtest_kwargs)
        markdown = (
            parser.layout_extractor.extract(report)
            if hasattr(parser.layout_extractor, "extract")
            else ""
        )
        # 含 formula_proxy 的提取不写 cache，避免无旗标复用
        from reproagent.reproducer.run_flags import get_run_flags

        if not get_run_flags().get("formula_proxy"):
            cache_manager.save(
                cache_key=cache_key,
                markdown=markdown,
                specs=specs,
                config=config,
            )
        cached_data = None

    # 3–6. Per-factor: reproduce → deviation → reflection → library
    from reproagent.library.experience_memory import ExperienceMemory

    experience_memory = ExperienceMemory(db_path=str(settings.db_path))
    memory_writer = None
    rma_summary: list[dict[str, Any]] = []
    if settings.memory_enabled:
        from reproagent.memory.store import MemoryStore
        from reproagent.memory.writer import MemoryWriter

        memory_writer = MemoryWriter(MemoryStore(repository), settings)
        try:
            rma_summary = memory_writer.absorb_specs(list(config.factor_specs), report.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RMA absorb_specs failed: %s", exc)

    data_loader = DataLoader(settings)
    reproducer = FactorReproducer(settings, data_loader)
    analyzer = DeviationAnalyzer()
    tolerances = ToleranceConfig()
    library_manager = FactorLibraryManager(repository, paths)
    reflection_controller = ReflectionLoopController(
        reproducer=reproducer,
        analyzer=analyzer,
        llm_extractor=parser.llm_extractor,
        config_builder=parser.config_builder,
        tolerances=tolerances,
        repository=repository,
        experience_memory=experience_memory,
        max_iterations=settings.max_reflection_iterations,
    )

    factor_results: list[dict[str, Any]] = []
    for spec in config.factor_specs:
        try:
            one = _process_one_factor(
                spec=spec,
                config=config,
                report=report,
                markdown=markdown,
                specs=specs if not cached_data else cached_data[1],
                cache_key=cache_key,
                cache_manager=cache_manager,
                cached_data=cached_data,
                reproducer=reproducer,
                analyzer=analyzer,
                tolerances=tolerances,
                library_manager=library_manager,
                reflection_controller=reflection_controller,
                repository=repository,
                logger=logger,
                experience_memory=experience_memory,
                memory_writer=memory_writer,
                pipeline_settings=settings,
            )
        except Exception as exc:  # noqa: BLE001
            from reproagent.exceptions import ConfigurationError

            if isinstance(exc, ConfigurationError):
                logger.error("Factor %s failed: %s", spec.factor_name, exc)
            else:
                logger.exception("Factor %s failed: %s", spec.factor_name, exc)
                repository.enqueue_review(
                    report.id, f"Factor {spec.factor_name} failed: {exc}"
                )
            one = {
                "factor_name": spec.factor_name,
                "status": "error",
                "error": str(exc),
            }
        factor_results.append(one)

    return _finalize_pipeline_result(
        overall=_aggregate_status(factor_results),
        factor_results=factor_results,
        report_id=report.id,
        source="pdf",
        rma=rma_summary,
        data_context=_data_context(settings, config),
    )


def _finalize_pipeline_result(
    *,
    overall: str,
    factor_results: list[dict[str, Any]],
    report_id: str | None = None,
    source: str = "pdf",
    rma: list[dict[str, Any]] | None = None,
    data_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一 CLI / pipeline 输出 schema。"""
    from reproagent.reproducer.run_flags import snapshot_run_flags

    flags = snapshot_run_flags()
    soft_any = any(
        r.get("soft_pass")
        or str(r.get("reflection_status") or "").startswith("soft_pass")
        for r in factor_results
    )
    out: dict[str, Any] = {
        "status": overall,
        "source": source,
        "report_id": report_id,
        "factors": factor_results,
        "factor_count": len(factor_results),
        "summary": {
            "total": len(factor_results),
            "passed": sum(1 for r in factor_results if r.get("status") == "passed"),
            "converged": sum(1 for r in factor_results if r.get("status") == "converged"),
            "soft_passed": sum(
                1 for r in factor_results if r.get("status") == "soft_passed"
            ),
            "review_enqueued": sum(
                1 for r in factor_results if r.get("status") == "review_enqueued"
            ),
            "errors": sum(1 for r in factor_results if r.get("status") == "error"),
        },
        # 可审计：供 batch 评分判定 full_no_fallback_success
        "rma": list(rma or []),
        "observability": {
            "formula_fallback": bool(flags.get("formula_fallback")),
            "formula_proxy": bool(flags.get("formula_proxy")),
            "universe_fallback": bool(flags.get("universe_fallback")),
            "soft_pass": soft_any or bool(flags.get("soft_pass")),
            "universe_fallback_reason": flags.get("universe_fallback_reason"),
            "proxy_factors": list(flags.get("proxy_factors") or []),
            "recovery_used": bool(flags.get("recovery_used")),
            "recovery_reasons": list(flags.get("recovery_reasons") or []),
        },
    }
    if data_context:
        out["data_context"] = data_context
    successes = [r for r in factor_results if r.get("factor_id")]
    if len(successes) == 1:
        out["factor_id"] = successes[0]["factor_id"]
    elif len(successes) > 1:
        out["factor_ids"] = [r["factor_id"] for r in successes]
    if overall == "review_enqueued" and factor_results:
        out["reflection_status"] = factor_results[0].get("reflection_status")
    return out


def reproduce_text(
    text: str,
    settings: Settings,
    *,
    title: str = "Markdown Input",
    broker: str = "unknown",
    backtest_kwargs: dict[str, Any] | None = None,
) -> dict | None:
    """端到端复现：直接对 Markdown/文本做 LLM 提取 → 复现 → 入库。

    跳过 PDF 解析步骤，适用于已有研报 Markdown 文本的场景。

    Parameters
    ----------
    text: 研报 Markdown 文本（或纯文本）。
    settings: 配置。
    title: 用于创建 ResearchReport 的标题。
    broker: 用于创建 ResearchReport 的券商名。
    """
    import logging
    import uuid
    from datetime import UTC, datetime

    from reproagent.cache.cache_manager import CacheManager
    from reproagent.deviation.analyzer import DeviationAnalyzer
    from reproagent.deviation.reflection_loop import ReflectionLoopController
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.models.deviation import ToleranceConfig
    from reproagent.models.report import ResearchReport
    from reproagent.parser.report_parser import ReportParser
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.reproducer.reproducer import FactorReproducer
    from reproagent.reproducer.run_flags import begin_run_flags
    from reproagent.utils.hashing import content_hash

    begin_run_flags()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()

    engine = get_engine(settings.db_path)
    init_db(engine)
    repository = Repository(engine)

    # 创建虚拟 ResearchReport（无真实 PDF）
    today = datetime.now(UTC).date()
    file_hash = content_hash(text)
    existing = repository.get_report_by_hash(file_hash)
    if existing is not None:
        report = existing
    else:
        report = ResearchReport(
            id=uuid.uuid4().hex,
            file_path=Path("markdown://input"),
            file_hash=file_hash,
            title=title,
            broker=broker,
            report_date=today,
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
        repository.save_report(report)

    cache_manager = CacheManager(paths)
    cache_key = _versioned_cache_key(report.file_hash, settings)

    # Parse from text (skip LayoutExtractor). 严格模式跳过 parse cache。
    parser = ReportParser(settings)
    cached_data = cache_manager.get_cached(cache_key)
    markdown = text
    use_parse_cache = cached_data is not None and bool(settings.formula_fallback_allowed)
    if use_parse_cache and cached_data is not None:
        _, specs, config = cached_data
        from reproagent.parser.config_builder import apply_backtest_kwargs

        config = apply_backtest_kwargs(config, backtest_kwargs)
        logger.info("Loaded parsing results from cache for %s", cache_key)
    else:
        if cached_data and not settings.formula_fallback_allowed:
            logger.info(
                "Strict mode: ignoring parse cache for %s (re-extract)", cache_key
            )
        try:
            specs = parser.parse_text(report, text)
        except ValueError as exc:
            reason = f"Schema validation failed for extracted factors: {exc}"
            repository.enqueue_review(report.id, reason)
            logger.warning("parse_text() rejected specs for %s: %s", report.id, exc)
            return _finalize_pipeline_result(
                overall="review_enqueued",
                factor_results=[],
                report_id=report.id,
                source="text",
            )
        if not specs:
            repository.enqueue_review(report.id, "No factors extracted from text")
            return _finalize_pipeline_result(
                overall="no_factors",
                factor_results=[],
                report_id=report.id,
                source="text",
            )
        config = parser.build_config(specs, report, backtest_kwargs=backtest_kwargs)
        from reproagent.reproducer.run_flags import get_run_flags

        if not get_run_flags().get("formula_proxy"):
            cache_manager.save(
                cache_key=cache_key,
                markdown=markdown,
                specs=specs,
                config=config,
            )
        cached_data = None

    # Per-factor reproduction (same as reproduce_report)
    from reproagent.library.experience_memory import ExperienceMemory

    experience_memory = ExperienceMemory(db_path=str(settings.db_path))
    memory_writer = None
    rma_summary: list[dict[str, Any]] = []
    if settings.memory_enabled:
        from reproagent.memory.store import MemoryStore
        from reproagent.memory.writer import MemoryWriter

        memory_writer = MemoryWriter(MemoryStore(repository), settings)
        try:
            rma_summary = memory_writer.absorb_specs(list(config.factor_specs), report.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RMA absorb_specs failed: %s", exc)

    data_loader = DataLoader(settings)
    reproducer = FactorReproducer(settings, data_loader)
    analyzer = DeviationAnalyzer()
    tolerances = ToleranceConfig()
    library_manager = FactorLibraryManager(repository, paths)
    reflection_controller = ReflectionLoopController(
        reproducer=reproducer,
        analyzer=analyzer,
        llm_extractor=parser.llm_extractor,
        config_builder=parser.config_builder,
        tolerances=tolerances,
        repository=repository,
        experience_memory=experience_memory,
        max_iterations=settings.max_reflection_iterations,
    )

    factor_results: list[dict[str, Any]] = []
    for spec in config.factor_specs:
        try:
            one = _process_one_factor(
                spec=spec,
                config=config,
                report=report,
                markdown=markdown,
                specs=specs if not cached_data else cached_data[1],
                cache_key=cache_key,
                cache_manager=cache_manager,
                cached_data=cached_data,
                reproducer=reproducer,
                analyzer=analyzer,
                tolerances=tolerances,
                library_manager=library_manager,
                reflection_controller=reflection_controller,
                repository=repository,
                logger=logger,
                experience_memory=experience_memory,
                memory_writer=memory_writer,
                pipeline_settings=settings,
            )
        except Exception as exc:  # noqa: BLE001
            from reproagent.exceptions import ConfigurationError

            if isinstance(exc, ConfigurationError):
                logger.error("Factor %s failed: %s", spec.factor_name, exc)
            else:
                logger.exception("Factor %s failed: %s", spec.factor_name, exc)
                repository.enqueue_review(
                    report.id, f"Factor {spec.factor_name} failed: {exc}"
                )
            one = {
                "factor_name": spec.factor_name,
                "status": "error",
                "error": str(exc),
            }
        factor_results.append(one)

    return _finalize_pipeline_result(
        overall=_aggregate_status(factor_results),
        factor_results=factor_results,
        report_id=report.id,
        source="text",
        rma=rma_summary,
        data_context=_data_context(settings, config),
    )
