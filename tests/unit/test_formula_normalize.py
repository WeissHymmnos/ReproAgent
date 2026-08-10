"""Honest normalize: empty/prose/coerce-to-close MUST set used_proxy=True."""

from __future__ import annotations

from reproagent.parser.formula_normalize import (
    coerce_unknown_names,
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


def test_mechanical_power_market_cap_executable_no_proxy() -> None:
    f, proxy, mech = normalize_formula(
        "Power(CSZScore(Log(total_market_cap)), 2)", allow_proxy=False
    )
    assert proxy is False
    assert is_executable(f)
    assert "market_cap" in f


def test_empty_formula_is_proxy() -> None:
    f, proxy, _ = normalize_formula("", factor_name="momentum", allow_proxy=False)
    assert proxy is True
    assert is_executable(f)


def test_prose_always_proxy_including_roe_name() -> None:
    """Skeptic: prose→ROE heuristic must still be used_proxy=True."""
    f, proxy, _ = normalize_formula(
        "R² = 1 - SSE/SST 残差叙述",
        factor_name="ROE_Factor",
        factor_name_cn="盈利能力",
        allow_proxy=False,
    )
    assert proxy is True
    assert "return_on_equity" in f or "close" in f


def test_prose_default_momentum_is_proxy() -> None:
    f, proxy, _ = normalize_formula(
        "这是一段无法解析的中文公式描述",
        factor_name="misc",
        allow_proxy=False,
    )
    assert proxy is True


def test_coerce_unknown_to_close_is_proxy() -> None:
    """Rank(weird) → Rank(close) must set used_proxy=True."""
    f, proxy, _ = normalize_formula("Rank(weird_unknown_field)", allow_proxy=False)
    assert proxy is True
    assert "close" in f
    assert is_executable(f)


def test_coerce_unknown_names_reports_replaced() -> None:
    out, replaced = coerce_unknown_names("Rank(weird)")
    assert replaced is True
    assert "close" in out
    out2, replaced2 = coerce_unknown_names("Rank(close)")
    assert replaced2 is False


def test_roe_alias_executable_no_proxy() -> None:
    f, proxy, _ = normalize_formula("CSZScore(roe)", allow_proxy=False)
    assert proxy is False
    assert "return_on_equity" in f
    assert is_executable(f)


def test_normalize_all_flags_universe_fallback() -> None:
    nr = normalize_all(
        formula="close/Ref(close,5)-1",
        universe="期货套利组合",
        allow_proxy=False,
    )
    assert nr.universe_fallback is True
    assert nr.used_proxy is False
    assert is_executable(nr.formula)


def test_mechanical_rewrite_power() -> None:
    s = mechanical_rewrite("Power(x, 2)")
    assert "Pow" in s


def test_unary_std_gets_default_window() -> None:
    """Std without window is mechanical → Std(..., 20); not proxy."""
    f, proxy, mech = normalize_formula(
        "-1*CSZScore(Std(close/Ref(close,1)-1))", allow_proxy=False
    )
    assert proxy is False
    assert is_executable(f)
    assert ", 20)" in f.replace(",20)", ", 20)") or ", 20" in f
    assert "Std" in f


def test_std_with_window_unchanged() -> None:
    f, proxy, _ = normalize_formula(
        "-1*CSZScore(Std(close/Ref(close,1)-1, 60))", allow_proxy=False
    )
    assert proxy is False
    assert "60" in f


def test_prose_empty_coerce_still_proxy() -> None:
    """Skeptic lock: empty/prose/coerce never sneak through as non-proxy."""
    _, p1, _ = normalize_formula("", factor_name="x")
    assert p1 is True
    _, p2, _ = normalize_formula("叙述性公式描述文字", factor_name="ROE")
    assert p2 is True
    _, p3, _ = normalize_formula("Rank(unknown_xyz)")
    assert p3 is True


def test_window_placeholder_n_is_mechanical_not_proxy() -> None:
    """Std(ret, N) → Std(ret, 20); not coerce N→close."""
    f, proxy, _ = normalize_formula("Std(close/Ref(close,1)-1, N)")
    assert proxy is False
    assert is_executable(f)
    assert "close)" not in f.replace("close/", "").replace("close,", "")
    assert ", 20)" in f.replace(",20)", ", 20)") or ", 20" in f


def test_upward_vol_ratio_with_n_executable() -> None:
    raw = "Sqrt(Sum(Max(close/Ref(close,1)-1,0)^2, N))/Sqrt(Sum((close/Ref(close,1)-1)^2, N))"
    f, proxy, _ = normalize_formula(raw)
    assert proxy is False
    assert is_executable(f)
    assert "N" not in f
