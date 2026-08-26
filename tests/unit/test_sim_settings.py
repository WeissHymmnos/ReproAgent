"""Delay, Decay, industry neutralization, truncation, slippage, limit no-fill."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams
from reproagent.reproducer.backtester import StrategyBacktester
from reproagent.reproducer.sim_transforms import (
    apply_decay,
    apply_delay_forward_returns,
    apply_limit_no_fill,
    apply_truncation,
    neutralize_factor_values,
)
from reproagent.settings import Settings


def _factor_def() -> FactorDefinition:
    return FactorDefinition(
        id="f1",
        spec_id="s1",
        name="f",
        name_cn="f",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="all",
        rebalance_frequency="daily",
    )


def test_industry_neutralization_differs_from_market_demean() -> None:
    fv = pl.DataFrame(
        {
            "date": [date(2020, 1, 2)] * 4,
            "asset": ["a", "b", "c", "d"],
            "factor_value": [1.0, 3.0, 10.0, 12.0],
        }
    )
    px = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 2)] * 4,
            "ts_code": ["a", "b", "c", "d"],
            "industry": ["I1", "I1", "I2", "I2"],
            "close": [10.0, 10.0, 10.0, 10.0],
        }
    )
    market = neutralize_factor_values(fv, px, "market")
    industry = neutralize_factor_values(fv, px, "industry")
    assert market["factor_value"].to_list() != industry["factor_value"].to_list()
    # I1 mean=2 → [-1, 1]; I2 mean=11 → [-1, 1]
    assert industry["factor_value"].to_list() == pytest.approx([-1.0, 1.0, -1.0, 1.0])


def test_delay_changes_forward_return() -> None:
    data = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)],
            "ts_code": ["a", "a", "a"],
            "close": [10.0, 11.0, 12.1],
        }
    )
    d1 = apply_delay_forward_returns(data, 1)
    d2 = apply_delay_forward_returns(data, 2)
    r1 = d1.filter(pl.col("trade_date") == date(2020, 1, 1))["forward_return"][0]
    r2 = d2.filter(pl.col("trade_date") == date(2020, 1, 1))["forward_return"][0]
    assert r1 == pytest.approx(0.1)
    assert r2 == pytest.approx(0.21)


def test_decay_changes_factor_path() -> None:
    fv = pl.DataFrame(
        {
            "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(4)],
            "asset": ["a"] * 4,
            "factor_value": [0.0, 0.0, 0.0, 10.0],
        }
    )
    raw = apply_decay(fv, 0)["factor_value"].to_list()
    smoothed = apply_decay(fv, 3)["factor_value"].to_list()
    assert raw[-1] == pytest.approx(10.0)
    assert smoothed[-1] != pytest.approx(10.0)


def test_truncation_caps_weight() -> None:
    w = pl.DataFrame(
        {
            "date": [date(2020, 1, 2), date(2020, 1, 2)],
            "asset": ["a", "b"],
            "weight": [0.5, -0.5],
        }
    )
    out = apply_truncation(w, 0.01)
    assert out["weight"].to_list() == pytest.approx([0.01, -0.01])


def test_limit_lock_bar_has_no_fill_non_limit_does() -> None:
    data = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 1), date(2020, 1, 2)],
            "ts_code": ["a", "a", "b", "b"],
            "close": [10.0, 11.0, 10.0, 10.5],
            "is_limit": [False, True, False, False],
        }
    )
    data = apply_delay_forward_returns(data, 1)
    filled = apply_limit_no_fill(data, 1)
    a = filled.filter((pl.col("ts_code") == "a") & (pl.col("trade_date") == date(2020, 1, 1)))
    b = filled.filter((pl.col("ts_code") == "b") & (pl.col("trade_date") == date(2020, 1, 1)))
    assert a["forward_return"][0] is None
    assert b["forward_return"][0] == pytest.approx(0.05)


def test_slippage_changes_net_return_vs_cost_only(tmp_path) -> None:
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(8)]
    assets = ["x", "y", "z", "w"]
    fv = pl.DataFrame(
        [
            {"date": d, "asset": a, "factor_value": float(j + i)}
            for i, d in enumerate(days)
            for j, a in enumerate(assets)
        ]
    )
    px = pl.DataFrame(
        [
            {
                "trade_date": d,
                "ts_code": a,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0 + i + 0.2 * j,
                "volume": 1_000_000.0,
            }
            for i, d in enumerate(days)
            for j, a in enumerate(assets)
        ]
    )
    settings = Settings(data_dir=tmp_path / "bt")
    bt = StrategyBacktester(settings)
    p0 = BacktestParams(
        start_date=days[0],
        end_date=days[-1],
        num_groups=2,
        transaction_cost_bps=3.0,
        slippage_bps=0.0,
        delay=1,
        limit_no_fill=False,
    )
    p1 = p0.model_copy(update={"slippage_bps": 10.0})
    r0 = bt.run(fv, p0, _factor_def(), data=px)
    r1 = bt.run(fv, p1, _factor_def(), data=px)
    assert r0.long_short_annual_return != r1.long_short_annual_return


def test_decay_changes_backtest_turnover(tmp_path) -> None:
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(10)]
    assets = ["x", "y", "z", "w"]
    fv = pl.DataFrame(
        [
            {"date": d, "asset": a, "factor_value": float((j + 1) * (i % 3))}
            for i, d in enumerate(days)
            for j, a in enumerate(assets)
        ]
    )
    px = pl.DataFrame(
        [
            {
                "trade_date": d,
                "ts_code": a,
                "close": 10.0 + 0.1 * i + j,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "volume": 1e6,
            }
            for i, d in enumerate(days)
            for j, a in enumerate(assets)
        ]
    )
    settings = Settings(data_dir=tmp_path / "bt2")
    bt = StrategyBacktester(settings)
    base = BacktestParams(
        start_date=days[0],
        end_date=days[-1],
        num_groups=2,
        delay=1,
        decay=0,
        limit_no_fill=False,
    )
    decayed = base.model_copy(update={"decay": 4})
    r0 = bt.run(fv, base, _factor_def(), data=px)
    r1 = bt.run(fv, decayed, _factor_def(), data=px)
    assert r0.turnover != r1.turnover or r0.ic_mean != r1.ic_mean
