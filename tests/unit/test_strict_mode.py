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
