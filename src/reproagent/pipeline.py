"""端到端流程编排：摄入 → 解析 → 复现 → 偏差 → 反思 → 入库。

支持一篇研报中的多个因子：逐个复现并汇总结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reproagent.settings import Settings


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
) -> dict[str, Any]:
    import uuid
    from datetime import UTC, datetime

    from reproagent.library.versioning import compute_dedup_hash
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.models.report import ReportedMetrics

    factor_config = _single_factor_config(config, spec)
    reported = spec.reported_metrics or ReportedMetrics()
    factor_name = spec.factor_name
    input_fields = [f.name for f in (spec.input_fields or [])]

    # 置信度门控：低置信 / 高 WARN 比例 → 人工复核，不自动复现入库
    from reproagent.parser.confidence import evaluate_confidence

    gate = evaluate_confidence(spec)
    if not gate.ok:
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

    cached_bt = cache_manager.get_cached_backtest(cache_key, factor_name)
    if cached_bt:
        result = cached_bt
        logger.info("Loaded backtest result from cache for %s", factor_name)
    else:
        result = reproducer.reproduce(factor_config)
        if cached_data is not None:
            cache_manager.save(cache_key, markdown, specs, config, result)

    deviation = analyzer.analyze(result, reported, tolerances)
    deviation.root_cause = analyzer.classify_root_cause(deviation, factor_config)

    if deviation.passed:
        factor_def, _ = reproducer.compute_factor(factor_config, spec)
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
        )
        saved = library_manager.register(entry)
        if experience_memory is not None:
            try:
                experience_memory.record_success(
                    formula=spec.formula,
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
            "metrics": {
                "ic_mean": result.ic_mean,
                "ic_ir": result.ic_ir,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "long_short_annual_return": result.long_short_annual_return,
            },
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
            )
            saved = library_manager.register(entry)
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

    reason = f"Reflection failed for {factor_name}: {state.status}"
    repository.enqueue_review(report.id, reason)
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
        "status": "review_enqueued",
        "reflection_status": state.status,
    }


def _aggregate_status(factor_results: list[dict[str, Any]]) -> str:
    if not factor_results:
        return "no_factors"
    statuses = {r["status"] for r in factor_results}
    success = {"passed", "converged"}
    if statuses <= success:
        return "passed" if "passed" in statuses or statuses == {"converged"} else "passed"
    if statuses & success:
        return "partial"
    if "review_enqueued" in statuses:
        return "review_enqueued"
    return next(iter(statuses))


def reproduce_report(pdf_path: Path, settings: Settings) -> dict | None:
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

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()

    engine = get_engine(settings.db_path)
    init_db(engine)

    repository = Repository(engine)

    # 1. Ingestion
    report = upload_pdf(pdf_path)
    report = validate_pdf(report)
    repository.save_report(report)

    if report.validation_status == "invalid":
        repository.enqueue_review(report.id, "PDF validation failed")
        return _finalize_pipeline_result(
            overall="invalid",
            factor_results=[],
            report_id=report.id,
            source="pdf",
        )

    cache_manager = CacheManager(paths)
    cache_key = report.file_hash

    # 2. Parse (with cache)
    parser = ReportParser(settings)
    cached_data = cache_manager.get_cached(cache_key)
    markdown = ""
    if cached_data:
        markdown, specs, config = cached_data
        logger.info("Loaded parsing results from cache for %s", cache_key)
    else:
        specs = parser.parse(report)
        if not specs:
            repository.enqueue_review(report.id, "No factors extracted")
            return _finalize_pipeline_result(
                overall="no_factors",
                factor_results=[],
                report_id=report.id,
                source="pdf",
            )
        config = parser.build_config(specs, report)
        markdown = (
            parser.layout_extractor.extract(report)
            if hasattr(parser.layout_extractor, "extract")
            else ""
        )
        cache_manager.save(
            cache_key=cache_key,
            markdown=markdown,
            specs=specs,
            config=config,
        )

    # 3–6. Per-factor: reproduce → deviation → reflection → library
    from reproagent.library.experience_memory import ExperienceMemory

    experience_memory = ExperienceMemory(db_path=str(settings.db_path))

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
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Factor %s failed: %s", spec.factor_name, exc)
            repository.enqueue_review(report.id, f"Factor {spec.factor_name} failed: {exc}")
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
    )


def _finalize_pipeline_result(
    *,
    overall: str,
    factor_results: list[dict[str, Any]],
    report_id: str | None = None,
    source: str = "pdf",
) -> dict[str, Any]:
    """统一 CLI / pipeline 输出 schema。"""
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
            "review_enqueued": sum(
                1 for r in factor_results if r.get("status") == "review_enqueued"
            ),
            "errors": sum(1 for r in factor_results if r.get("status") == "error"),
        },
    }
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
    from reproagent.utils.hashing import content_hash

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()

    engine = get_engine(settings.db_path)
    init_db(engine)
    repository = Repository(engine)

    # 创建虚拟 ResearchReport（无真实 PDF）
    today = datetime.now(UTC).date()
    report = ResearchReport(
        id=uuid.uuid4().hex,
        file_path=Path("markdown://input"),
        file_hash=content_hash(text),
        title=title,
        broker=broker,
        report_date=today,
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repository.save_report(report)

    cache_manager = CacheManager(paths)
    cache_key = report.file_hash

    # Parse from text (skip LayoutExtractor)
    parser = ReportParser(settings)
    cached_data = cache_manager.get_cached(cache_key)
    markdown = text
    if cached_data:
        _, specs, config = cached_data
        logger.info("Loaded parsing results from cache for %s", cache_key)
    else:
        specs = parser.parse_text(report, text)
        if not specs:
            repository.enqueue_review(report.id, "No factors extracted from text")
            return _finalize_pipeline_result(
                overall="no_factors",
                factor_results=[],
                report_id=report.id,
                source="text",
            )
        config = parser.build_config(specs, report)
        cache_manager.save(
            cache_key=cache_key,
            markdown=markdown,
            specs=specs,
            config=config,
        )

    # Per-factor reproduction (same as reproduce_report)
    from reproagent.library.experience_memory import ExperienceMemory

    experience_memory = ExperienceMemory(db_path=str(settings.db_path))

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
            )
        except Exception as exc:
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
    )
