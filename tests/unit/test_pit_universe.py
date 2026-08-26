"""PIT universe, survivorship, and fundamental announcement lag."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from reproagent.reproducer.data_loader import _NAMED_UNIVERSE_INDEX, DataLoader
from reproagent.reproducer.pit import (
    apply_announcement_lag,
    apply_point_in_time,
    apply_survivorship_filter,
    is_full_market_universe,
)
from reproagent.settings import Settings


def test_all_is_not_csi300_proxy() -> None:
    assert "all" not in _NAMED_UNIVERSE_INDEX
    assert "全a" not in _NAMED_UNIVERSE_INDEX
    assert is_full_market_universe("all") is True
    assert is_full_market_universe("全A股") is True
    assert is_full_market_universe("csi300") is False


def test_survivorship_keeps_post_list_drops_pre_list_and_post_delist() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [
                date(2020, 1, 1),
                date(2020, 1, 2),
                date(2020, 1, 3),
                date(2020, 1, 4),
            ],
            "ts_code": ["AAA", "AAA", "AAA", "AAA"],
            "close": [1.0, 2.0, 3.0, 4.0],
            "list_date": [date(2020, 1, 2)] * 4,
            "delist_date": [date(2020, 1, 4)] * 4,
        }
    )
    out = apply_survivorship_filter(df)
    kept = out["trade_date"].to_list()
    assert date(2020, 1, 1) not in kept  # before list
    assert date(2020, 1, 2) in kept
    assert date(2020, 1, 3) in kept
    assert date(2020, 1, 4) not in kept  # delist day gone


def test_delisted_name_stays_before_delist() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2021, 6, 1), date(2021, 6, 2)],
            "ts_code": ["DEAD", "DEAD"],
            "close": [10.0, 9.0],
            "delist_date": [date(2021, 6, 2), date(2021, 6, 2)],
        }
    )
    out = apply_survivorship_filter(df)
    assert out["trade_date"].to_list() == [date(2021, 6, 1)]


def test_fundamental_before_ann_date_nulled() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2022, 4, 1), date(2022, 4, 30)],
            "ts_code": ["AAA", "AAA"],
            "pe_ttm": [12.0, 12.0],
            "ann_date": [date(2022, 4, 20), date(2022, 4, 20)],
        }
    )
    out = apply_announcement_lag(df)
    assert out["pe_ttm"].to_list()[0] is None
    assert out["pe_ttm"].to_list()[1] == pytest.approx(12.0)


def test_loader_applies_pit_on_local_panel(tmp_path) -> None:
    prices = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)],
            "ts_code": ["AAA", "AAA", "AAA"],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 2.0, 3.0],
            "volume": [100.0, 100.0, 100.0],
            "list_date": [date(2020, 1, 2)] * 3,
            "delist_date": [date(2020, 1, 3)] * 3,
            "pe_ttm": [8.0, 8.0, 8.0],
            "ann_date": [date(2020, 1, 2)] * 3,
        }
    )
    prices.write_parquet(tmp_path / "prices.parquet")
    loader = DataLoader(Settings(data_source="local", local_data_path=tmp_path))
    out = loader.load_price_data("all", date(2020, 1, 1), date(2020, 1, 3))
    assert date(2020, 1, 1) not in out["trade_date"].to_list()
    assert date(2020, 1, 3) not in out["trade_date"].to_list()
    assert out["pe_ttm"].to_list() == pytest.approx([8.0])


def test_ricequant_all_uses_all_instruments_not_csi300() -> None:
    from datetime import date as d

    settings = Settings(data_source="ricequant")
    loader = DataLoader(settings)
    import pandas as pd

    fake_rq = MagicMock()
    fake_rq.all_instruments.return_value = pd.DataFrame(
        {"order_book_id": ["000001.XSHE", "999999.XSHE"]}
    )
    with patch.object(loader, "_ensure_rqdatac_init", return_value=fake_rq):
        codes = loader._resolve_ricequant_instruments("all", as_of=d(2020, 6, 1))
    assert codes == ["000001.XSHE", "999999.XSHE"]
    fake_rq.all_instruments.assert_called()
    fake_rq.index_components.assert_not_called()


def test_point_in_time_noop_without_optional_columns() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2)],
            "ts_code": ["AAA"],
            "close": [1.0],
        }
    )
    out = apply_point_in_time(df)
    assert out.height == 1
