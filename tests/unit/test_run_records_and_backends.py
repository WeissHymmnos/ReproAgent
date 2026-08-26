"""运行记录；parser / rqalpha 后端选了未实现的就报错。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from reproagent.exceptions import ConfigurationError
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.parser.layout_extractor import LayoutExtractor
from reproagent.persistence.run_log import list_run_records, write_run_record
from reproagent.reproducer.evaluator_factory import build_evaluator
from reproagent.reproducer.rqalpha_engine import RiceQuantEval
from reproagent.settings import Settings


def test_two_reproduce_text_attempts_write_two_run_records(tmp_path) -> None:
    from pathlib import Path

    from reproagent.persistence.run_log import list_run_records
    from reproagent.pipeline import reproduce_text

    settings = Settings(
        data_source="local",
        local_data_path=Path("tests/fixtures/test_data"),
        data_dir=tmp_path / "data",
        allow_mock_llm=True,
    )
    body = "动量因子：close / Ref(close, 5) - 1"
    first = reproduce_text(body, settings, title="a")
    second = reproduce_text(body, settings, title="b")
    assert first is not None and second is not None
    recs = list_run_records(settings.data_dir)
    assert len(recs) >= 2
    ids = {r["id"] for r in recs}
    assert len(ids) >= 2


def test_two_run_records_are_distinct(tmp_path) -> None:
    write_run_record(
        tmp_path,
        {
            "id": "r1",
            "formula": "close",
            "window": {"start": "2020-01-01", "end": "2020-12-31"},
            "kind": "reproduce",
        },
    )
    write_run_record(
        tmp_path,
        {
            "id": "r2",
            "formula": "Ref(close,1)",
            "window": {"start": "2020-01-01", "end": "2020-12-31"},
            "kind": "reflection",
        },
    )
    recs = list_run_records(tmp_path)
    assert len(recs) == 2
    ids = {r["id"] for r in recs}
    assert ids == {"r1", "r2"}
    formulas = {r["formula"] for r in recs}
    assert formulas == {"close", "Ref(close,1)"}


def test_rqalpha_engine_fail_closed_no_polars() -> None:
    cfg = ReplicationConfig(
        id="c",
        report_id="r",
        factor_specs=[],
        engine="rqalpha",
        data_source="local",
        backtest_params=BacktestParams(start_date=date(2020, 1, 1), end_date=date(2020, 2, 1)),
        parser_version="1",
        extraction_model_id="x",
        created_at=datetime.now(UTC),
    )
    engine = build_evaluator(cfg)
    assert isinstance(engine, RiceQuantEval)
    fdef = FactorDefinition(
        id="f",
        spec_id="s",
        name="n",
        name_cn="n",
        style="other",
        formula="close",
        input_fields=[],
        universe="all",
        rebalance_frequency="daily",
    )
    with pytest.raises(ConfigurationError, match="not implemented"):
        engine.compute(fdef, "all", date(2020, 1, 1), date(2020, 2, 1), data=None)


def test_unimplemented_parser_backend_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(parser_backend="marker")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(parser_backend="llamaparse")  # type: ignore[arg-type]
    extractor = LayoutExtractor(backend="finpdfpro")
    extractor.backend = "marker"  # type: ignore[assignment]
    with pytest.raises(ConfigurationError, match="Only finpdfpro"):
        extractor.extract(object())  # type: ignore[arg-type]


def test_default_engine_is_polars_only() -> None:
    from typing import get_args

    assert set(get_args(Settings.model_fields["default_engine"].annotation)) == {"polars"}
    assert set(get_args(Settings.model_fields["parser_backend"].annotation)) == {"finpdfpro"}
    assert Settings().default_engine == "polars"
