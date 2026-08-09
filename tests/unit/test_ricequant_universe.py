"""Structural + unit tests for ricequant universe resolution (no live network required)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from reproagent.reproducer.data_loader import (
    DataLoader,
    _normalize_rq_order_book_id,
    is_cb_universe,
)
from reproagent.settings import Settings


def test_normalize_rq_order_book_id() -> None:
    assert _normalize_rq_order_book_id("000001.SZ") == "000001.XSHE"
    assert _normalize_rq_order_book_id("600000.SH") == "600000.XSHG"
    assert _normalize_rq_order_book_id("000001.XSHE") == "000001.XSHE"
    assert _normalize_rq_order_book_id("600519") == "600519.XSHG"


def test_is_cb_universe() -> None:
    assert is_cb_universe("全转债") is True
    assert is_cb_universe("csi300") is False


def test_resolve_named_universe_uses_index_components(tmp_path, monkeypatch) -> None:
    settings = Settings(data_source="ricequant")
    loader = DataLoader(settings)

    fake_rq = MagicMock()
    fake_rq.index_components.return_value = ["000001.XSHE", "600000.XSHG"]

    # Isolate from host disk instrument cache
    import reproagent.reproducer.data_loader as dl_mod

    monkeypatch.setattr(dl_mod, "_RQ_INST_CACHE_DIR", tmp_path / "inst")

    with patch.object(loader, "_ensure_rqdatac_init", return_value=fake_rq):
        codes = loader._resolve_ricequant_instruments("csi300", as_of=date(2024, 6, 1))
    assert codes == ["000001.XSHE", "600000.XSHG"]
    fake_rq.index_components.assert_called()


def test_unrecognized_universe_hard_fails() -> None:
    from reproagent.exceptions import ReproductionError

    settings = Settings(data_source="ricequant")
    loader = DataLoader(settings)
    fake_rq = MagicMock()
    with patch.object(loader, "_ensure_rqdatac_init", return_value=fake_rq):
        with pytest.raises(ReproductionError, match="Unrecognized"):
            loader._resolve_ricequant_instruments("中信一级行业XYZ", as_of=date(2024, 6, 1))


def test_load_ricequant_price_maps_columns() -> None:
    import pandas as pd

    settings = Settings(data_source="ricequant")
    loader = DataLoader(settings)

    # Clear process cache side effects
    from reproagent.reproducer import data_loader as dl_mod

    dl_mod._RQ_PRICE_CACHE.clear()

    idx = pd.MultiIndex.from_product(
        [["000001.XSHE"], pd.to_datetime(["2024-01-02", "2024-01-03"])],
        names=["order_book_id", "date"],
    )
    pdf = pd.DataFrame(
        {
            "open": [10.0, 10.5],
            "high": [11.0, 11.5],
            "low": [9.0, 9.5],
            "close": [10.2, 10.8],
            "volume": [1e6, 1.1e6],
            "total_turnover": [1e7, 1.1e7],
        },
        index=idx,
    )

    fake_rq = MagicMock()
    fake_rq.get_price.return_value = pdf

    with (
        patch.object(loader, "_ensure_rqdatac_init", return_value=fake_rq),
        patch.object(
            loader,
            "_resolve_ricequant_instruments",
            return_value=["000001.XSHE"],
        ),
    ):
        out = loader._load_ricequant_price("csi300", date(2024, 1, 2), date(2024, 1, 3))

    assert isinstance(out, pl.DataFrame)
    assert out.height == 2
    assert "trade_date" in out.columns
    assert "ts_code" in out.columns
    assert "close" in out.columns
    assert "amount" in out.columns


def test_unary_minus_formula() -> None:
    from datetime import UTC, date as d, datetime

    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.replication import BacktestParams, ReplicationConfig
    from reproagent.reproducer.polars_engine import PolarsEngine

    cfg = ReplicationConfig(
        id="t",
        report_id="r",
        factor_specs=[],
        engine="polars",
        data_source="local",
        backtest_params=BacktestParams(start_date=d(2024, 1, 1), end_date=d(2024, 1, 10)),
        parser_version="1.0.0",
        extraction_model_id="test",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(cfg, allow_formula_fallback=False)
    data = pl.DataFrame(
        {
            "trade_date": [d(2024, 1, 2), d(2024, 1, 3)] * 2,
            "ts_code": ["a", "a", "b", "b"],
            "open": [1.0, 1.1, 2.0, 2.1],
            "high": [1.0, 1.1, 2.0, 2.1],
            "low": [1.0, 1.1, 2.0, 2.1],
            "close": [10.0, 11.0, 20.0, 22.0],
            "volume": [100.0] * 4,
        }
    )
    fdef = FactorDefinition(
        id="f",
        spec_id="f",
        name="neg_mom",
        name_cn="负动量",
        style="momentum",
        formula="-1 * (close / Ref(close, 1) - 1)",
        input_fields=["close"],
        universe="csi300",
        rebalance_frequency="monthly",
    )
    out = engine.compute(fdef, "csi300", d(2024, 1, 1), d(2024, 1, 10), data=data)
    assert out.height >= 1
    assert "factor_value" in out.columns
