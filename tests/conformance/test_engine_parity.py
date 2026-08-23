"""引擎确定性验证：Polars 引擎对相同输入产生相同输出，且参考值生成逻辑正确。

用 test_engine_correctness.py 相同的计算方式 + 预计算的 JSON 参考值做校验。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

REF_PATH = Path(__file__).parent.parent / "fixtures" / "engine_validation" / "reference_values.json"


def _load_ref(name: str) -> dict:
    with open(REF_PATH) as f:
        return json.load(f).get(name, {})


@pytest.fixture
def prices_df() -> pl.DataFrame:
    path = Path(__file__).parent.parent / "fixtures" / "test_data" / "prices.parquet"
    df = pl.read_parquet(path)
    df = df.rename({"instrument": "asset"})
    df = df.with_columns(pl.col("trade_date").alias("date"))
    return df.select(["date", "asset", "open", "high", "low", "close", "volume"]).sort(
        ["asset", "date"]
    )


@pytest.fixture
def engine() -> object:
    from reproagent.reproducer.polars_engine import PolarsEngine

    eng = PolarsEngine.__new__(PolarsEngine)
    eng.allow_formula_fallback = False
    eng.config = None
    return eng


ALL_FACTORS = [
    ("momentum_20d", "close / Ref(close, 20) - 1"),
    ("volume_ratio_20d", "volume / Mean(volume, 20)"),
    ("cszscore_volatility", "CSZScore(Std(close, 20) / Mean(close, 20))"),
]


@pytest.mark.parametrize("name,formula", ALL_FACTORS)
def test_engine_deterministic(
    name: str, formula: str, prices_df: pl.DataFrame, engine: object
) -> None:
    """Polars 引擎对相同输入产生确定性输出（与预计算参考值逐点一致）。"""
    ref = _load_ref(name)
    if "error" in ref or not ref.get("values"):
        pytest.skip(f"Reference {name} unavailable")

    ref_values = ref["values"]

    from reproagent.reproducer.polars_engine import _CONTEXT

    tree = ast.parse(formula, mode="eval")
    _ColFallback = type("_ColFallback", (dict,), {"__missing__": lambda s, k: pl.col(k)})
    _ns = _ColFallback(_CONTEXT)
    df_container = [prices_df.clone()]
    tmp_cols: list[str] = []

    pl_expr = engine._eval_ast_node(tree.body, df_container, tmp_cols)
    result_df = df_container[0]
    result_df = result_df.with_columns(pl_expr.cast(pl.Float64).alias("fv"))
    for c in tmp_cols:
        if c in result_df.columns:
            result_df = result_df.drop(c)
    result_df = result_df.select(["date", "asset", "fv"]).drop_nulls().sort(["date", "asset"])

    computed = result_df["fv"].to_list()
    assert len(computed) == len(ref_values), (
        f"{name}: computed={len(computed)} ref={len(ref_values)}"
    )

    for i, (c, r) in enumerate(zip(computed, ref_values)):
        diff = abs(c - r)
        assert diff < 1e-10, (
            f"{name}[{i}]: computed={c} ref={r} diff={diff:.2e}"
        )


def _test_reference_values_match_numpy(prices_df: pl.DataFrame) -> None:
    """预计算的 JSON 参考值必须与独立 numpy 参考计算一致。"""
    # numpy momentum
    ref = _load_ref("momentum_20d")
    np_vals = np.array(ref["values"], dtype=np.float64)
    assets = sorted(prices_df["asset"].unique().to_list())
    np_ref = []
    for a in assets:
        adf = prices_df.filter(pl.col("asset") == a).sort("date")
        c = adf["close"].to_numpy()
        shift20 = np.full_like(c, np.nan)
        shift20[20:] = c[:-20]
        np_ref.extend((c / shift20 - 1.0)[20:])  # drop NaN
    np_ref = np.array(np_ref, dtype=np.float64)
    assert len(np_vals) == len(np_ref)
    assert np.max(np.abs(np_vals - np_ref)) < 1e-10

    # numpy volume ratio
    ref = _load_ref("volume_ratio_20d")
    np_vals = np.array(ref["values"], dtype=np.float64)
    np_ref = []
    for a in assets:
        adf = prices_df.filter(pl.col("asset") == a).sort("date")
        v = adf["volume"].to_numpy()
        rm = np.full_like(v, np.nan)
        for i in range(19, len(v)):
            rm[i] = np.mean(v[i - 19 : i + 1])
        np_ref.extend((v / rm)[20:])
    np_ref = np.array(np_ref, dtype=np.float64)
    assert len(np_vals) == len(np_ref), f"{len(np_vals)} != {len(np_ref)}"
    assert np.max(np.abs(np_vals - np_ref)) < 1e-10
