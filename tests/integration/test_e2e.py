"""端到端：离线 pipeline（mock LLM + local data）跑通摄入→解析→复现→偏差。

`reproagent.pipeline.reproduce_report` 编排器尚未实现（见 masterplan §9 / Task 24），
因此本测试直接串联已实现的子系统组件，验证离线全链路在 mock+local 下可跑通，
不依赖真实 LLM / ricequant / qlib 凭证。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reproagent.deviation.analyzer import DeviationAnalyzer
from reproagent.ingestion.uploader import upload_pdf
from reproagent.ingestion.validator import validate_pdf
from reproagent.models.deviation import ToleranceConfig
from reproagent.parser.report_parser import ReportParser
from reproagent.reproducer.data_loader import DataLoader
from reproagent.reproducer.reproducer import FactorReproducer
from reproagent.settings import Settings


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="",
        parser_backend="finpdfpro",
        data_source="local",
        local_data_path=Path("tests/fixtures/test_data"),
        data_dir=tmp_path / "reproagent-e2e",
    )


def test_e2e_offline_pipeline_mock_local(sample_report_path: Path, offline_settings: Settings) -> None:
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