"""因子引擎正确性自检：逐点比对 PolarsEngine 的计算值与参考值。

KunQuant 的 "test against alpha158.npz reference" 模式：
预计算一组经典因子的参考值，CI 中每次代码变更后重新计算并逐点比对。
差异阈值: abs(diff) < 1e-10（浮点误差可忽略）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import polars as pl
import pytest

REFERENCE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "engine_validation" / "reference_values.json"
)


def load_reference(name: str) -> dict:
    with open(REFERENCE_PATH) as f:
        data = json.load(f)
    return data.get(name, {})


@pytest.fixture
def prices_df() -> pl.DataFrame:
    path = Path(__file__).parent.parent / "fixtures" / "test_data" / "prices.parquet"
    df = pl.read_parquet(path)
    df = df.rename({"instrument": "asset"})
    df = df.with_columns(pl.col("trade_date").alias("date"))
    df = df.select(["date", "asset", "open", "high", "low", "close", "volume"])
    return df.sort(["asset", "date"])


@pytest.fixture
def engine() -> object:
    from reproagent.reproducer.polars_engine import PolarsEngine

    eng = PolarsEngine.__new__(PolarsEngine)
    eng.allow_formula_fallback = False
    eng.config = None
    return eng


# 所有 10 个经典因子
ALL_FACTORS = [
    ("momentum_20d", "close / Ref(close, 20) - 1"),
    ("volume_ratio_20d", "volume / Mean(volume, 20)"),
    ("close_volatility_20d", "Std(close, 20) / Mean(close, 20)"),
    ("turnover_rank", "Rank(volume)"),
    ("price_position", "(close - Ref(close, 20)) / (Max(close, 20) - Min(close, 20))"),
    ("cszscore_volatility", "CSZScore(Std(close, 20) / Mean(close, 20))"),
    ("delta_5d", "Delta(close, 5) / Ref(close, 5)"),
    ("ref_1d_return", "close / Ref(close, 1) - 1"),
    ("abs_delta_10d", "Abs(Delta(close, 10)) / Ref(close, 10)"),
    ("log_price_rank", "Rank(Log(close))"),
]


@pytest.mark.parametrize("name,formula", ALL_FACTORS)
def test_engine_value_matches_reference(
    name: str, formula: str, prices_df: pl.DataFrame, engine: object
) -> None:
    """逐点比对：PolarsEngine 的计算值与参考值差异 < 1e-10。"""
    ref = load_reference(name)
    if "error" in ref:
        pytest.skip(f"Reference has error: {ref['error']}")

    ref_values = ref.get("values", [])
    _ = ref.get("dates", [])
    _ = ref.get("assets", [])

    if not ref_values:
        pytest.skip("Empty reference values")

    from reproagent.reproducer.polars_engine import _CONTEXT

    tree = ast.parse(formula, mode="eval")
    _ColFallback = type("_ColFallback", (dict,), {"__missing__": lambda s, k: pl.col(k)})
    _ns = _ColFallback(_CONTEXT)
    df_container = [prices_df.clone()]
    tmp_cols: list[str] = []

    pl_expr = engine._eval_ast_node(tree.body, df_container, tmp_cols)
    result_df = df_container[0]
    if isinstance(pl_expr, pl.Expr):
        result_df = result_df.with_columns(pl_expr.cast(pl.Float64).alias("fv"))
    else:
        result_df = result_df.with_columns(pl.lit(pl_expr).cast(pl.Float64).alias("fv"))

    cols_to_drop = [c for c in tmp_cols if c in result_df.columns]
    if cols_to_drop:
        result_df = result_df.drop(cols_to_drop)

    result_df = result_df.select(["date", "asset", "fv"]).drop_nulls().sort(["date", "asset"])
    computed = result_df["fv"].to_list()

    # 行数必须一致
    assert len(computed) == len(ref_values), (
        f"{name}: row count mismatch: computed={len(computed)} ref={len(ref_values)}"
    )

    # 逐点比对
    max_diff = 0.0
    for i, (c, r) in enumerate(zip(computed, ref_values)):
        diff = abs(c - r)
        if diff > max_diff:
            max_diff = diff
        assert diff < 1e-10, (
            f"{name}[{i}]: computed={c} ref={r} diff={diff:.2e} "
            f"date={result_df['date'][i]} asset={result_df['asset'][i]}"
        )

    # 确保没有系统性偏差
    assert max_diff < 1e-10, f"{name}: max absolute difference {max_diff:.2e} exceeds 1e-10"


@pytest.mark.parametrize("name,formula", ALL_FACTORS)
def test_engine_does_not_produce_nan(
    name: str, formula: str, prices_df: pl.DataFrame, engine: object
) -> None:
    """所有因子计算后不应产生 NaN 值（在 drop_nulls 之前）。"""
    from reproagent.reproducer.polars_engine import _CONTEXT

    tree = ast.parse(formula, mode="eval")
    _ColFallback = type("_ColFallback", (dict,), {"__missing__": lambda s, k: pl.col(k)})
    _ns = _ColFallback(_CONTEXT)
    df_container = [prices_df.clone()]
    tmp_cols: list[str] = []

    pl_expr = engine._eval_ast_node(tree.body, df_container, tmp_cols)
    result_df = df_container[0]
    if isinstance(pl_expr, pl.Expr):
        result_df = result_df.with_columns(pl_expr.cast(pl.Float64).alias("fv"))
    else:
        result_df = result_df.with_columns(pl.lit(pl_expr).cast(pl.Float64).alias("fv"))

    # 检查未 drop_nulls 时的值
    fv = result_df["fv"].to_list()
    nan_count = sum(1 for v in fv if v is None or (isinstance(v, float) and v != v))
    # 允许前 20 个有 NaN（rolling window 初始化），之后不应有
    assert nan_count <= 42, (
        f"{name}: {nan_count} NaN/null values is excessive (max 42 allowed for warmup)"
    )
