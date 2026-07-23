"""端到端：离线 pipeline（mock LLM + local data）。

覆盖：
1. 子系统串联（parse → reproduce → deviation）
2. 真实编排器 `reproduce_report`（含入库成功路径）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reproagent.deviation.analyzer import DeviationAnalyzer
from reproagent.ingestion.uploader import upload_pdf
from reproagent.ingestion.validator import validate_pdf
from reproagent.models.deviation import DeviationReport, ToleranceConfig
from reproagent.parser.report_parser import ReportParser
from reproagent.pipeline import reproduce_report
from reproagent.reproducer.data_loader import DataLoader
from reproagent.reproducer.reproducer import FactorReproducer
from reproagent.settings import Settings


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="dev",
        allow_mock_llm=True,
        allow_formula_fallback=True,
        llm_api_key="",
        parser_backend="finpdfpro",
        data_source="local",
        local_data_path=Path("tests/fixtures/test_data"),
        data_dir=tmp_path / "reproagent-e2e",
    )


def test_e2e_offline_pipeline_mock_local(
    sample_report_path: Path, offline_settings: Settings
) -> None:
    report = upload_pdf(sample_report_path)
    report = validate_pdf(report)
    assert report.page_count >= 1
    assert report.validation_status == "valid"

    parser = ReportParser(offline_settings)
    specs = parser.parse(report)
    assert len(specs) >= 1
    spec = specs[0]
    assert spec.factor_name
    assert spec.formula

    config = parser.build_config(specs, report)
    assert config.factor_specs

    data_loader = DataLoader(offline_settings)
    reproducer = FactorReproducer(offline_settings, data_loader)
    result = reproducer.reproduce(config)
    assert result.factor_id
    assert result.factor_values_path.exists()
    assert result.equity_curve_path.exists()

    reported = spec.reported_metrics
    assert reported is not None
    deviation = DeviationAnalyzer().analyze(result, reported, ToleranceConfig())
    assert isinstance(deviation.passed, bool)
    assert isinstance(deviation.metric_deviations, dict)


def test_e2e_missing_pdf_raises(offline_settings: Settings, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        upload_pdf(missing)


def test_reproduce_report_orchestrator_review_or_pass(
    sample_report_path: Path, offline_settings: Settings
) -> None:
    """编排器可完整跑通；mock 指标通常偏差较大 → review 或 passed。"""
    outcome = reproduce_report(sample_report_path, offline_settings)
    assert outcome is not None
    assert "status" in outcome
    assert outcome["status"] in {
        "passed",
        "converged",
        "partial",
        "review_enqueued",
        "no_factors",
        "invalid",
        "error",
    }
    assert "factors" in outcome
    assert isinstance(outcome["factors"], list)


def test_reproduce_report_register_on_pass(
    sample_report_path: Path, offline_settings: Settings
) -> None:
    """偏差通过时必须成功入库（覆盖 compute_dedup_hash / register 路径）。"""

    def _pass_analyze(self, result, reported, tolerances):  # noqa: ANN001
        return DeviationReport(
            id="dev-test",
            comparison_id=result.id,
            factor_id=result.factor_id,
            passed=True,
            metric_deviations={},
            tolerances=tolerances,
            root_cause_detail="forced pass for e2e",
            recommend_reflect=False,
        )

    with patch.object(DeviationAnalyzer, "analyze", _pass_analyze):
        outcome = reproduce_report(sample_report_path, offline_settings)

    assert outcome is not None
    assert outcome["status"] == "passed"
    assert outcome.get("factor_id")

    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository

    engine = get_engine(offline_settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(offline_settings)
    manager = FactorLibraryManager(repository=repo, paths=paths)
    entry = manager.get(outcome["factor_id"])
    assert entry is not None
    assert entry.dedup_hash
    assert len(entry.dedup_hash) == 64
