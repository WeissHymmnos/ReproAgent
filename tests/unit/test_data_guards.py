"""数据口径守卫单元测试。"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from reproagent.reproducer.data_guards import (
    DataGuardConfig,
    DataGuardStats,
    _filter_limit_hit,
    _filter_new_listings,
    _filter_st,
    _filter_suspended,
    _normalize_columns,
    apply_guards,
    validate_adjustment,
)

# ── helpers ──

_BASE_DATE = date(2023, 1, 1)


def _make_df(
    n_rows: int = 10,
    *,
    with_name: bool = False,
    with_volume_zero: bool = False,
    with_list_date: bool = False,
    with_pre_close: bool = False,
    with_adj: bool = False,
) -> pl.DataFrame:
    """构建可配置的测试 DataFrame。"""
    ts_code = ["000001.SZ", "600000.SH"]
    rows = []
    for i in range(n_rows):
        code = ts_code[i % 2]
        row: dict = {
            "trade_date": _BASE_DATE + timedelta(days=i),
            "ts_code": code,
            "open": 10.0 + i * 0.1,
            "high": 11.0 + i * 0.1,
            "low": 9.5 + i * 0.1,
            "close": 10.5 + i * 0.1,
            "volume": 0.0 if with_volume_zero and i == 0 else 1000000.0 + i * 10000,
        }
        if with_name:
            row["name"] = "*ST 平安" if i == 0 else "平安银行"
        if with_list_date:
            row["list_date"] = date(2022, 12, 31) if i > 0 else _BASE_DATE
        if with_pre_close:
            row["pre_close"] = 10.0 + i * 0.1
        if with_adj:
            row["adj_factor"] = 1.0 if i < 5 else 0.8
        rows.append(row)
    return pl.DataFrame(rows)


# ── column normalization ──


class TestColumnNormalization:
    def test_renames_date_to_trade_date(self) -> None:
        df = pl.DataFrame({"date": [date(2023, 1, 1)], "close": [10.0]})
        result = _normalize_columns(df)
        assert "trade_date" in result.columns

    def test_renames_asset_to_ts_code(self) -> None:
        df = pl.DataFrame({"asset": ["000001.SZ"], "close": [10.0]})
        result = _normalize_columns(df)
        assert "ts_code" in result.columns

    def test_preserves_existing_columns(self) -> None:
        df = pl.DataFrame({"trade_date": [date(2023, 1, 1)], "close": [10.0]})
        result = _normalize_columns(df)
        assert result.columns == ["trade_date", "close"]


# ── ST filter ──


class TestFilterST:
    def test_removes_st_by_name(self) -> None:
        df = _make_df(4, with_name=True)
        result, removed = _filter_st(df)
        assert removed == 1
        assert len(result) == 3

    def test_removes_st_by_ts_code(self) -> None:
        df = pl.DataFrame(
            {
                "ts_code": ["000001.SZ", "*ST平安", "600000.SH"],
                "close": [10.0, 10.0, 10.0],
            }
        )
        result, removed = _filter_st(df)
        assert removed == 1

    def test_normal_stock_untouched(self) -> None:
        df = _make_df(4)
        result, removed = _filter_st(df)
        assert removed == 0
        assert len(result) == 4


# ── suspended filter ──


class TestFilterSuspended:
    def test_removes_zero_volume(self) -> None:
        df = _make_df(4, with_volume_zero=True)
        result, removed = _filter_suspended(df)
        assert removed == 1
        assert len(result) == 3

    def test_keeps_positive_volume(self) -> None:
        df = _make_df(4)
        result, removed = _filter_suspended(df)
        assert removed == 0


# ── new listings filter ──


class TestFilterNewListings:
    def test_removes_recent_ipo(self) -> None:
        df = _make_df(4, with_list_date=True)
        # trade_date starts 2023-01-01, first row list_date is also 2023-01-01
        # so min_listing_days=60 should remove it
        result, removed = _filter_new_listings(df, 60)
        assert removed >= 1

    def test_skip_when_no_list_date(self) -> None:
        df = _make_df(4)
        result, removed = _filter_new_listings(df, 60)
        assert removed == 0

    def test_min_days_zero_removes_nothing(self) -> None:
        df = _make_df(4, with_list_date=True)
        result, removed = _filter_new_listings(df, 0)
        assert removed == 0


# ── limit hit filter ──


class TestFilterLimitHit:
    def test_removes_limit_up(self) -> None:
        config = DataGuardConfig()
        df = pl.DataFrame(
            {
                "trade_date": [date(2023, 1, 1), date(2023, 1, 2)],
                "ts_code": ["000001.SZ", "000001.SZ"],
                "close": [10.0, 11.0],
                "pre_close": [10.0, 10.0],
            }
        )
        result, up, down = _filter_limit_hit(df, config)
        # close 11.0, pre_close 10.0 → return = 0.10 > 0.098
        assert up == 1
        assert len(result) == 1

    def test_normal_day_untouched(self) -> None:
        config = DataGuardConfig()
        df = pl.DataFrame(
            {
                "trade_date": [date(2023, 1, 1), date(2023, 1, 2)],
                "ts_code": ["000001.SZ", "000001.SZ"],
                "close": [10.0, 10.05],
                "pre_close": [10.0, 10.0],
            }
        )
        result, up, down = _filter_limit_hit(df, config)
        assert up == 0
        assert down == 0
        assert len(result) == 2

    def test_first_bar_without_pre_close_is_kept(self) -> None:
        """Shifted pre_close is null on day 1; that is not a limit-up/down hit."""
        config = DataGuardConfig()
        df = pl.DataFrame(
            {
                "trade_date": [
                    date(2023, 1, 2),
                    date(2023, 1, 3),
                    date(2023, 1, 2),
                    date(2023, 1, 3),
                ],
                "ts_code": ["000001.SZ", "000001.SZ", "600000.SH", "600000.SH"],
                "close": [10.0, 10.05, 15.0, 15.04],
            }
        )
        result, up, down = _filter_limit_hit(df, config)
        assert up == 0
        assert down == 0
        assert len(result) == 4
        assert result["trade_date"].to_list().count(date(2023, 1, 2)) == 2


# ── adjustment validation ──


class TestValidateAdjustment:
    def test_constant_adj_factor_is_unadjusted(self) -> None:
        df = pl.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 5,
                "close": [10.0, 11.0, 12.0, 13.0, 14.0],
                "adj_factor": [1.0] * 5,
            }
        )
        valid, _msg = validate_adjustment(df)
        assert not valid

    def test_varying_adj_factor_is_adjusted(self) -> None:
        df = pl.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 5,
                "close": [10.0, 11.0, 12.0, 13.0, 14.0],
                "adj_factor": [1.0, 1.0, 0.8, 0.8, 0.8],
            }
        )
        valid, _msg = validate_adjustment(df)
        assert valid


# ── end-to-end apply_guards ──


class TestApplyGuards:
    def test_full_pipeline_no_errors(self) -> None:
        df = _make_df(10)
        result, stats = apply_guards(df)
        assert isinstance(result, pl.DataFrame)
        assert isinstance(stats, DataGuardStats)
        assert stats.total_before == 10
        assert stats.total_after <= 10

    def test_guards_with_st_data(self) -> None:
        df = _make_df(6, with_name=True)
        config = DataGuardConfig(
            filter_st=True,
            filter_suspended=True,
            min_listing_days=0,
            filter_limit_up_down=False,
            require_forward_adjusted=False,
        )
        result, stats = apply_guards(df, config)
        assert stats.st_removed == 1
        assert stats.total_after == 5

    def test_custom_config_disables_all(self) -> None:
        df = _make_df(4, with_name=True, with_volume_zero=True)
        config = DataGuardConfig(
            filter_st=False,
            filter_suspended=False,
            min_listing_days=0,
            filter_limit_up_down=False,
            require_forward_adjusted=False,
        )
        result, stats = apply_guards(df, config)
        assert stats.total_before == stats.total_after

    def test_stats_total_accounting(self) -> None:
        df = _make_df(20, with_name=True)
        config = DataGuardConfig(
            filter_st=True,
            filter_suspended=False,
            min_listing_days=0,
            filter_limit_up_down=False,
            require_forward_adjusted=False,
        )
        result, stats = apply_guards(df, config)
        assert stats.total_after == stats.total_before - stats.st_removed - stats.suspended_removed

    def test_apply_guards_accounts_for_fixture_first_session(self) -> None:
        from pathlib import Path

        path = Path("tests/fixtures/test_data/prices.parquet")
        if not path.exists():
            import pytest

            pytest.skip("fixture prices.parquet missing")
        df = pl.read_parquet(path)
        result, stats = apply_guards(df)
        accounted = (
            stats.st_removed
            + stats.suspended_removed
            + stats.new_listing_removed
            + stats.limit_up_removed
            + stats.limit_down_removed
        )
        assert stats.total_after == stats.total_before - accounted
        assert stats.total_after == result.height
        # Session-1 rows must survive when they are not actual limit hits.
        first = df["trade_date"].min()
        assert result.filter(pl.col("trade_date") == first).height == df.filter(
            pl.col("trade_date") == first
        ).height
