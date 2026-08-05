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
) -> dict[str, Any]:
    import uuid
    from datetime import UTC, datetime

    from reproagent.library.versioning import compute_dedup_hash
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.models.report import ReportedMetrics

    factor_config = _single_factor_config(config, spec)
    reported = spec.reported_metrics or ReportedMetrics()
    factor_name = spec.factor_name

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
            version="0.1.0",
            dedup_hash=compute_dedup_hash(factor_def),
            created_at=datetime.now(UTC),
        )
        saved = library_manager.register(entry)
        return {
            "factor_name": factor_name,
            "status": "passed",
            "factor_id": saved.id,
            "backtest_result_id": result.id,
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
                version="0.1.0",
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
            return {
                "factor_name": factor_name,
                "status": "converged",
                "factor_id": saved.id,
                "reflection_status": state.status,
            }

    reason = f"Reflection failed for {factor_name}: {state.status}"
    repository.enqueue_review(report.id, reason)
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
        return {"status": "invalid", "factors": []}

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
            return {"status": "no_factors", "factors": []}
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

    overall = _aggregate_status(factor_results)
    out: dict[str, Any] = {
        "status": overall,
        "factors": factor_results,
        "factor_count": len(factor_results),
    }
    # 向后兼容：单因子时保留 factor_id / reflection_status 顶层字段
    successes = [r for r in factor_results if r.get("factor_id")]
    if len(successes) == 1:
        out["factor_id"] = successes[0]["factor_id"]
    elif len(successes) > 1:
        out["factor_ids"] = [r["factor_id"] for r in successes]
    if overall == "review_enqueued" and factor_results:
        out["reflection_status"] = factor_results[0].get("reflection_status")
    return out
