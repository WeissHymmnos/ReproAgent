"""严格模式：prod 禁 mock、公式硬失败。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from reproagent.exceptions import FormulaError, LLMError
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.reproducer.polars_engine import PolarsEngine
from reproagent.settings import Settings


def test_prod_disallows_mock_llm_extract() -> None:
    settings = Settings(
        _env_file=None,
        app_env="prod",
        llm_api_key="",
        allow_mock_llm=None,
    )
    assert settings.mock_llm_allowed is False
    ex = LLMExtractor(settings)
    with pytest.raises(LLMError, match="mock LLM is disabled"):
        ex.extract(
            __import__("reproagent.models.report", fromlist=["ResearchReport"]).ResearchReport(
                id="r",
                file_path=Path("/tmp/x.pdf"),
                file_hash="h",
                page_count=1,
                ingested_at=datetime.now(UTC),
            ),
            "# md",
        )


def test_dev_allows_mock_llm() -> None:
    settings = Settings(_env_file=None, app_env="dev", llm_api_key="")
    assert settings.mock_llm_allowed is True
    specs = LLMExtractor(settings).extract(
        __import__("reproagent.models.report", fromlist=["ResearchReport"]).ResearchReport(
            id="r",
            file_path=Path("/tmp/x.pdf"),
            file_hash="h",
            page_count=1,
            ingested_at=datetime.now(UTC),
        ),
        "",
    )
    assert specs[0].factor_name == "mock_momentum"


def test_formula_strict_raises_on_syntax_error() -> None:
    config = ReplicationConfig(
        id="c1",
        report_id="r1",
        factor_specs=[],
        backtest_params=BacktestParams(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 10),
        ),
        parser_version="t",
        extraction_model_id="t",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(config, allow_formula_fallback=False)
    data = pl.DataFrame(
        {
            "date": [date(2020, 1, 1), date(2020, 1, 2)],
            "asset": ["A", "A"],
            "close": [1.0, 1.1],
        }
    )
    fd = FactorDefinition(
        id="f",
        spec_id="s",
        name="bad",
        name_cn="坏",
        style="other",
        formula="close / (  # broken",
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )
    with pytest.raises(FormulaError):
        engine.compute(fd, "all", date(2020, 1, 1), date(2020, 1, 10), data=data)


def test_blank_allow_mock_llm_env_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """ALLOW_MOCK_LLM= must not crash Settings; prod still forbids mock."""
    from reproagent.settings import get_settings

    monkeypatch.setenv("ALLOW_MOCK_LLM", "")
    monkeypatch.setenv("ALLOW_FORMULA_FALLBACK", "")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    try:
        settings = Settings(_env_file=None)
        assert settings.allow_mock_llm is None
        assert settings.allow_formula_fallback is None
        assert settings.is_prod is True
        assert settings.mock_llm_allowed is False
        assert settings.formula_fallback_allowed is False
        assert settings.llm_api_key.get_secret_value().strip() == ""
    finally:
        get_settings.cache_clear()


def test_cli_prod_reproduce_without_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("ALLOW_MOCK_LLM", raising=False)
    get_settings.cache_clear()
    pdf = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "sample_reports"
        / "minimal.pdf"
    )
    assert pdf.is_file()
    try:
        result = CliRunner().invoke(app, ["reproduce", str(pdf)])
        assert result.exit_code == 1
        out = f"{result.output}{result.stdout}{result.stderr}"
        assert "LLM_API_KEY" in out
        assert "reproduce failed" in out
    finally:
        get_settings.cache_clear()


def test_cli_prod_text_without_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    md = tmp_path / "a.md"
    md.write_text("动量因子：close / Ref(close, 5) - 1\n", encoding="utf-8")
    try:
        result = CliRunner().invoke(app, ["text", "-f", str(md)])
        assert result.exit_code == 1
        assert "LLM_API_KEY" in result.output
        assert "text failed" in result.output
    finally:
        get_settings.cache_clear()


def test_formula_fallback_returns_close() -> None:
    config = ReplicationConfig(
        id="c1",
        report_id="r1",
        factor_specs=[],
        backtest_params=BacktestParams(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 10),
        ),
        parser_version="t",
        extraction_model_id="t",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(config, allow_formula_fallback=True)
    data = pl.DataFrame(
        {
            "date": [date(2020, 1, 1), date(2020, 1, 2)],
            "asset": ["A", "A"],
            "close": [1.0, 1.1],
        }
    )
    fd = FactorDefinition(
        id="f",
        spec_id="s",
        name="bad",
        name_cn="坏",
        style="other",
        formula="close / (  # broken",
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )
    out = engine.compute(fd, "all", date(2020, 1, 1), date(2020, 1, 10), data=data)
    assert "factor_value" in out.columns
    assert out["factor_value"].to_list() == [1.0, 1.1]


def test_style_classifier_preserves_explicit_style() -> None:
    from reproagent.library.classifier import StyleClassifier

    fd = FactorDefinition(
        id="f",
        spec_id="s",
        name="something_unrelated",
        name_cn="无关",
        style="value",
        formula="close",
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )
    assert StyleClassifier().classify(fd) == "value"
    assert StyleClassifier().classify(fd, force=True) == "other"
