"""Honest normalize: mechanical rewrite vs proxy fallback flags."""

from __future__ import annotations

from reproagent.parser.formula_normalize import (
    is_executable,
    mechanical_rewrite,
    normalize_all,
    normalize_formula,
    normalize_universe,
)


def test_known_universe_not_fallback() -> None:
    u, fb = normalize_universe("全A股")
    assert u == "csi300" and fb is False
    u, fb = normalize_universe("csi500")
    assert u == "csi500" and fb is False


def test_unknown_universe_is_fallback() -> None:
    u, fb = normalize_universe("商品期货")
    assert u == "csi300" and fb is True
    u, fb = normalize_universe("中信一级行业XYZ")
    assert fb is True


def test_mechanical_power_market_cap_executable() -> None:
    f, proxy, mech = normalize_formula(
        "Power(CSZScore(Log(total_market_cap)), 2)", allow_proxy=False
    )
    assert proxy is False
    assert is_executable(f)
    assert "market_cap" in f


def test_strict_no_proxy_on_prose() -> None:
    f, proxy, _ = normalize_formula(
        "R² = 1 - SSE/SST 残差",
        factor_name="vol",
        allow_proxy=False,
    )
    assert proxy is False
    assert not is_executable(f) or f  # kept as non-exec or prose


def test_allow_proxy_marks_proxy() -> None:
    f, proxy, _ = normalize_formula("", factor_name="momentum", allow_proxy=True)
    assert proxy is True
    assert "close" in f or "Ref" in f


def test_normalize_all_flags_universe_fallback() -> None:
    nr = normalize_all(
        formula="close/Ref(close,5)-1",
        universe="期货套利组合",
        allow_proxy=False,
    )
    assert nr.universe_fallback is True
    assert nr.used_proxy is False
    assert is_executable(nr.formula)


def test_roe_alias_executable() -> None:
    f = mechanical_rewrite("CSZScore(roe)")
    assert "return_on_equity" in f
    assert is_executable(f)
