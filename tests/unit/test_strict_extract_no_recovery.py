"""Strict mode: no keep-first / force-reextract / silent CSI300 theater."""

from __future__ import annotations

from reproagent.parser.formula_normalize import normalize_all, normalize_formula
from reproagent.reproducer.run_flags import (
    begin_run_flags,
    get_run_flags,
    mark_recovery_used,
)


def test_empty_prose_unknown_are_proxy() -> None:
    assert normalize_formula("")[1] is True
    assert normalize_formula("这是叙述性描述无法解析")[1] is True
    assert normalize_formula("Rank(unknown_xyz_field)")[1] is True


def test_mechanical_std_window_not_proxy() -> None:
    f, proxy, _ = normalize_formula("-1*CSZScore(Std(close/Ref(close,1)-1))")
    assert proxy is False
    assert "20" in f


def test_unknown_universe_marks_fallback() -> None:
    nr = normalize_all(
        formula="close/Ref(close,5)-1",
        universe="商品期货套利池XYZ",
        allow_proxy=False,
    )
    assert nr.universe_fallback is True


def test_recovery_used_sets_proxy_bits() -> None:
    begin_run_flags()
    mark_recovery_used("dev_domain_proxy")
    flags = get_run_flags()
    assert flags["recovery_used"] is True
    assert flags["formula_proxy"] is True
    assert flags["formula_fallback"] is True


def test_known_universe_not_fallback() -> None:
    nr = normalize_all(
        formula="CSZScore(return_on_equity)",
        universe="csi500",
        allow_proxy=False,
    )
    assert nr.universe_fallback is False
    assert nr.used_proxy is False
    assert nr.universe == "csi500"
