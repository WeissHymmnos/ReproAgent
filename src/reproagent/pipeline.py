"""端到端流程编排（masterplan §9）。

实现时按注释步骤填充；当前为桩，便于后续填空。
"""

from __future__ import annotations

from pathlib import Path

from reproagent.settings import Settings


def reproduce_report(pdf_path: Path, settings: Settings) -> dict | None:
    import logging
    import uuid
    from datetime import UTC, datetime
    
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.ingestion.uploader import upload_pdf
    from reproagent.ingestion.validator import validate_pdf
    from reproagent.parser.report_parser import ReportParser
    from reproagent.parser.config_builder import ConfigBuilder
    from reproagent.parser.llm_extractor import LLMExtractor
    from reproagent.reproducer.reproducer import FactorReproducer
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.deviation.analyzer import DeviationAnalyzer
    from reproagent.deviation.reflection_loop import ReflectionLoopController
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.models.deviation import ToleranceConfig
    from reproagent.models.report import ReportedMetrics
    from reproagent.models.library import FactorLibraryEntry
    
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
        return {"status": "invalid"}
        
    # 2. Parse
    parser = ReportParser(settings)
    specs = parser.parse(report)
    if not specs:
        repository.enqueue_review(report.id, "No factors extracted")
        return {"status": "no_factors"}
    config = parser.build_config(specs, report)
        
    # 3. Reproduce
    data_loader = DataLoader(settings)
    reproducer = FactorReproducer(settings, data_loader)
    
    # 4. Deviation
    analyzer = DeviationAnalyzer()
    tolerances = ToleranceConfig()
    
    # 5. Library
    library_manager = FactorLibraryManager(repository, paths)
    
    # 6. Reflection
    reflection_controller = ReflectionLoopController(
        reproducer=reproducer,
        analyzer=analyzer,
        llm_extractor=parser.llm_extractor,
        config_builder=parser.config_builder,
        tolerances=tolerances,
        repository=repository,
    )
    
    spec = config.factor_specs[0]
    reported = spec.reported_metrics or ReportedMetrics()
    
    result = reproducer.reproduce(config)
    deviation = analyzer.analyze(result, reported, tolerances)
    deviation.root_cause = analyzer.classify_root_cause(deviation, config)
    
    if deviation.passed:
        factor_def, _ = reproducer.compute_factor(config, spec)
        entry = FactorLibraryEntry(
            id=uuid.uuid4().hex,
            factor=factor_def,
            report_id=report.id,
            config_id=config.id,
            backtest_result_id=result.id,
            deviation_passed=True,
            version="0.1.0",
            dedup_hash="",
            created_at=datetime.now(UTC),
        )
        library_manager.register(entry)
        return {"status": "passed", "factor_id": entry.id}
    else:
        state = reflection_controller.run(config, reported)
        if state.status == "converged":
            best_step = next((s for s in state.steps if s.id == state.best_step_id), None)
            if best_step:
                factor_def, _ = reproducer.compute_factor(best_step.revised_config, best_step.revised_config.factor_specs[0])
                entry = FactorLibraryEntry(
                    id=uuid.uuid4().hex,
                    factor=factor_def,
                    report_id=report.id,
                    config_id=best_step.revised_config.id,
                    backtest_result_id=best_step.deviation_report.comparison_id if best_step.deviation_report else uuid.uuid4().hex,
                    deviation_passed=True,
                    version="0.1.0",
                    dedup_hash="",
                    created_at=datetime.now(UTC),
                )
                library_manager.register(entry)
                return {"status": "converged", "factor_id": entry.id}
        
        repository.enqueue_review(report.id, f"Reflection failed: {state.status}")
        return {"status": "review_enqueued", "reflection_status": state.status}
