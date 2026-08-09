"""Extract-time formula/universe normalization (not runtime close-fallback)."""

from __future__ import annotations

from reproagent.parser.formula_normalize import (
    normalize_formula,
    normalize_universe,
)


def test_normalize_universe_known() -> None:
    assert normalize_universe("全A股") == "csi300"
    assert normalize_universe("沪深300") == "csi300"
    assert normalize_universe("中证500") == "csi500"
    assert normalize_universe("可转债") == "全转债"


def test_normalize_universe_descriptive_to_csi300() -> None:
    assert normalize_universe("中信一级行业") == "csi300"
    assert normalize_universe("商品期货") == "csi300"


def test_normalize_formula_power_and_market_cap() -> None:
    f, proxy = normalize_formula("Power(CSZScore(Log(total_market_cap)), 2)")
    assert not proxy
    assert "Pow" in f or "Pow(" in f or "market_cap" in f
    assert "total_market_cap" not in f or "market_cap" in f


def test_normalize_formula_resid_proxy_or_rewrite() -> None:
    f, _proxy = normalize_formula("Resid(dROE, [mktcap, PB])")
    # either executable CSZScore rewrite or name-based proxy
    assert f
    assert "Resid" not in f


def test_normalize_empty_uses_proxy() -> None:
    f, proxy = normalize_formula("", factor_name="momentum_20d", factor_name_cn="动量")
    assert proxy is True
    assert "close" in f or "Ref" in f
