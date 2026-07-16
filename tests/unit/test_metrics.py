"""Unit tests for reproagent.reproducer.metrics (sharpe / max_drawdown / ic)."""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from reproagent.reproducer.metrics import (
    compute_group_returns,
    compute_ic,
    compute_max_drawdown,
    compute_sharpe,
)


def test_compute_sharpe_zero_std_returns_zero() -> None:
    s = pl.Series("r", [0.01, 0.01, 0.01])
    assert compute_sharpe(s) == 0.0


def test_compute_sharpe_empty_returns_zero() -> None:
    s = pl.Series("r", [])
    assert compute_sharpe(s) == 0.0


def test_compute_sharpe_positive_for_positive_mean() -> None:
    s = pl.Series("r", [0.01, 0.02, -0.005, 0.015, 0.008])
    val = compute_sharpe(s)
    assert isinstance(val, float)
    assert val > 0


def test_compute_sharpe_daily_annualization_factor() -> None:
    s = pl.Series("r", [0.001, 0.002, -0.001, 0.0, 0.0015])
    daily = compute_sharpe(s, freq="daily")
    other = compute_sharpe(s, freq="monthly")
    assert daily > other


def test_compute_max_drawdown_zero_for_empty() -> None:
    s = pl.Series("e", [])
    assert compute_max_drawdown(s) == 0.0


def test_compute_max_drawdown_monotonic_increasing_zero() -> None:
    s = pl.Series("e", [1.0, 1.1, 1.2, 1.3])
    assert compute_max_drawdown(s) == 0.0


def test_compute_max_drawdown_nonnegative() -> None:
    s = pl.Series("e", [1.0, 0.9, 1.1, 0.8, 1.2])
    mdd = compute_max_drawdown(s)
    assert isinstance(mdd, float)
    assert mdd >= 0.0
    assert mdd <= 1.0


def test_compute_max_drawdown_known_value() -> None:
    s = pl.Series("e", [1.0, 0.8, 0.9])
    mdd = compute_max_drawdown(s)
    assert math.isclose(mdd, 0.2, rel_tol=1e-9)


def test_compute_ic_returns_dataframe_with_date_ic() -> None:
    factor_values = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 2)],
        "asset": ["A", "B", "A", "B"],
        "factor_value": [0.1, 0.2, 0.3, 0.4],
    })
    forward_returns = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 2)],
        "asset": ["A", "B", "A", "B"],
        "forward_return": [0.01, 0.02, 0.03, 0.04],
    })
    ic_df = compute_ic(factor_values, forward_returns)
    assert set(ic_df.columns) == {"date", "ic"}
    assert len(ic_df) == 2


def test_compute_ic_perfect_correlation() -> None:
    factor_values = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1)],
        "asset": ["A", "B"],
        "factor_value": [1.0, 2.0],
    })
    forward_returns = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1)],
        "asset": ["A", "B"],
        "forward_return": [1.0, 2.0],
    })
    ic_df = compute_ic(factor_values, forward_returns)
    assert len(ic_df) == 1
    assert math.isclose(ic_df["ic"][0], 1.0, abs_tol=1e-6)


def test_compute_group_returns_returns_dict() -> None:
    grouped = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 2)],
        "asset": ["A", "B", "A", "B"],
        "factor_value": [0.1, 0.2, 0.3, 0.4],
        "group": [0, 1, 0, 1],
    })
    returns = pl.DataFrame({
        "date": [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 2)],
        "asset": ["A", "B", "A", "B"],
        "forward_return": [0.01, 0.02, 0.03, 0.04],
    })
    gr = compute_group_returns(grouped, returns, num_groups=2)
    assert isinstance(gr, dict)
    assert set(gr) == {0, 1}


def test_compute_sharpe_finite_float() -> None:
    s = pl.Series("r", [0.01, -0.02, 0.005, 0.015, -0.001, 0.008])
    val = compute_sharpe(s)
    assert isinstance(val, float)
    assert math.isfinite(val)