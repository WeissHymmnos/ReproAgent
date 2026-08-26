"""Delay / Decay / 中性化 / 截断 / 涨跌停不成交。"""

from __future__ import annotations

import polars as pl


def _asset_col(df: pl.DataFrame) -> str:
    if "ts_code" in df.columns:
        return "ts_code"
    if "asset" in df.columns:
        return "asset"
    raise ValueError("panel needs ts_code or asset")


def _date_col(df: pl.DataFrame) -> str:
    if "trade_date" in df.columns:
        return "trade_date"
    if "date" in df.columns:
        return "date"
    raise ValueError("panel needs trade_date or date")


def mark_limit_locks(
    data: pl.DataFrame, *, up: float = 0.098, down: float = -0.098
) -> pl.DataFrame:
    """补 ``is_limit`` 列（True = 该 bar 不成交）。"""
    if data.is_empty():
        return data
    if "is_limit" in data.columns:
        return data
    if "limit_up" in data.columns or "limit_down" in data.columns:
        up_c = pl.col("limit_up").fill_null(False) if "limit_up" in data.columns else pl.lit(False)
        dn_c = (
            pl.col("limit_down").fill_null(False) if "limit_down" in data.columns else pl.lit(False)
        )
        return data.with_columns((up_c | dn_c).alias("is_limit"))

    asset = _asset_col(data)
    date_c = _date_col(data)
    df = data.sort([asset, date_c])
    if "pre_close" not in df.columns and "close" in df.columns:
        df = df.with_columns(pl.col("close").shift(1).over(asset).alias("pre_close"))
    if "pre_close" not in df.columns or "close" not in df.columns:
        return df.with_columns(pl.lit(False).alias("is_limit"))
    ret = (pl.col("close") / pl.col("pre_close") - 1.0)
    return df.with_columns(
        ((ret >= up) | (ret <= down)).fill_null(False).alias("is_limit")
    )


def apply_delay_forward_returns(data: pl.DataFrame, delay: int) -> pl.DataFrame:
    """``forward_return`` = close[t+delay]/close[t]-1. delay=1 is next-session."""
    delay = max(0, int(delay))
    asset = _asset_col(data)
    date_c = _date_col(data)
    df = data.sort([asset, date_c])
    if "close" not in df.columns:
        raise ValueError("price panel needs close")
    if delay == 0:
        return df.with_columns(pl.lit(0.0).alias("forward_return"))
    return df.with_columns(
        pl.when(pl.col("close").abs() > 1e-12)
        .then(pl.col("close").shift(-delay).over(asset) / pl.col("close") - 1)
        .otherwise(None)
        .alias("forward_return")
    )


def apply_limit_no_fill(data: pl.DataFrame, delay: int) -> pl.DataFrame:
    """Zero/null the forward return when the fill bar (t+delay) is limit-locked."""
    if data.is_empty() or "forward_return" not in data.columns:
        return data
    delay = max(0, int(delay))
    df = mark_limit_locks(data)
    asset = _asset_col(df)
    fill_limit = pl.col("is_limit").shift(-delay).over(asset) if delay else pl.col("is_limit")
    return df.with_columns(
        pl.when(fill_limit.fill_null(False))
        .then(pl.lit(None))
        .otherwise(pl.col("forward_return"))
        .alias("forward_return")
    )


def apply_decay(factor_values: pl.DataFrame, decay: int) -> pl.DataFrame:
    """因子值线性衰减平滑。decay<=1 不改动。"""
    decay = int(decay or 0)
    if decay <= 1 or factor_values.is_empty() or "factor_value" not in factor_values.columns:
        return factor_values
    asset = "asset" if "asset" in factor_values.columns else _asset_col(factor_values)
    date_c = "date" if "date" in factor_values.columns else _date_col(factor_values)
    df = factor_values.sort([asset, date_c])
    expr = pl.lit(0.0)
    wsum = decay * (decay + 1) / 2.0
    for i in range(decay):
        weight = float(decay - i)
        expr = expr + weight * pl.col("factor_value").shift(i).over(asset)
    return df.with_columns((expr / wsum).alias("factor_value"))


def neutralize_factor_values(
    factor_values: pl.DataFrame,
    data: pl.DataFrame | None,
    method: str | None,
) -> pl.DataFrame:
    """Cross-sectional demean: market (date) or industry/subindustry."""
    method = (method or "none").lower()
    if method in {"", "none"} or factor_values.is_empty():
        return factor_values
    fv = factor_values
    date_c = "date" if "date" in fv.columns else _date_col(fv)
    asset_c = "asset" if "asset" in fv.columns else _asset_col(fv)

    if method == "market":
        return fv.with_columns(
            (pl.col("factor_value") - pl.col("factor_value").mean().over(date_c)).alias(
                "factor_value"
            )
        )

    group_col = "industry" if method == "industry" else "subindustry"
    panel = fv
    if group_col not in panel.columns and data is not None and group_col in data.columns:
        d_col = _date_col(data)
        a_col = _asset_col(data)
        meta = data.select(
            [pl.col(d_col).alias(date_c), pl.col(a_col).alias(asset_c), group_col]
        ).unique(subset=[date_c, asset_c])
        panel = panel.join(meta, on=[date_c, asset_c], how="left")
    if group_col not in panel.columns:
        return neutralize_factor_values(fv, data, "market")
    return panel.with_columns(
        (
            pl.col("factor_value")
            - pl.col("factor_value").mean().over([date_c, group_col])
        ).alias("factor_value")
    )


def apply_truncation(weights: pl.DataFrame, truncation: float | None) -> pl.DataFrame:
    """把 |weight| 限制在 truncation 以内。"""
    if truncation is None or float(truncation) <= 0 or weights.is_empty():
        return weights
    cap = float(truncation)
    return weights.with_columns(pl.col("weight").clip(-cap, cap).alias("weight"))


def cost_rate_bps(transaction_cost_bps: float, slippage_bps: float) -> float:
    return (float(transaction_cost_bps) + float(slippage_bps)) / 10000.0
