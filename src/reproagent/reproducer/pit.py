"""Point-in-time universe membership and fundamental announcement lag.

Optional columns on a price/fundamental panel:
- ``list_date`` / ``ipo_date``: name is absent before listing
- ``delist_date``: name is absent on/after delist
- ``in_universe``: boolean membership for that row's date
- ``ann_date``: fundamental fields are invisible before announcement
"""

from __future__ import annotations

import polars as pl

# 全市场名。不要把这些键映射成沪深300。
FULL_MARKET_UNIVERSE_KEYS: frozenset[str] = frozenset(
    {
        "all",
        "全a股",
        "全a",
        "a股",
        "全市场",
    }
)

CSI300_UNIVERSE_KEYS: frozenset[str] = frozenset(
    {"csi300", "hs300", "沪深300"}
)

FUNDAMENTAL_COLUMNS: frozenset[str] = frozenset(
    {
        "pe_ttm",
        "pe_ratio",
        "pb",
        "pb_ratio",
        "ps_ttm",
        "ps_ratio",
        "roe_ttm",
        "return_on_equity",
        "roa_ttm",
        "return_on_asset",
        "market_cap",
        "float_market_cap",
        "turnover_rate",
        "dividend_yield",
        "grossprofit_margin",
        "netprofit_margin",
        "revenue_yoy",
        "profit_yoy",
        "debt_to_equity",
        "current_ratio",
        "eps",
        "net_profit",
        "operating_revenue",
        "book_value",
        "book_value_per_share",
        "ytm",
        "premium_rate",
        "bond_value",
        "implied_vol",
        "option_value",
        "remaining_size",
        "conversion_price",
    }
)


def normalize_universe_key(universe: str | None) -> str:
    return (universe or "").strip().lower().replace(" ", "")


def is_full_market_universe(universe: str | list[str] | None) -> bool:
    if isinstance(universe, list):
        return False
    return normalize_universe_key(universe) in FULL_MARKET_UNIVERSE_KEYS


def _date_col(df: pl.DataFrame) -> str:
    if "trade_date" in df.columns:
        return "trade_date"
    if "date" in df.columns:
        return "date"
    raise ValueError("panel needs trade_date or date")


def _as_date_col(df: pl.DataFrame, col: str) -> pl.DataFrame:
    if col not in df.columns:
        return df
    dtype = df.schema[col]
    if dtype == pl.Utf8:
        return df.with_columns(pl.col(col).str.to_date())
    if dtype == pl.Datetime:
        return df.with_columns(pl.col(col).dt.date())
    return df


def apply_survivorship_filter(df: pl.DataFrame) -> pl.DataFrame:
    """按行日期过滤未上市 / 已退市。没有相关列则原样返回。"""
    if df.is_empty():
        return df
    df = df.clone()
    date_col = _date_col(df)
    df = _as_date_col(df, date_col)

    list_col = None
    if "list_date" in df.columns:
        list_col = "list_date"
    elif "ipo_date" in df.columns:
        list_col = "ipo_date"
    if list_col:
        df = _as_date_col(df, list_col)
        df = df.filter(pl.col(list_col).is_null() | (pl.col(date_col) >= pl.col(list_col)))

    if "delist_date" in df.columns:
        df = _as_date_col(df, "delist_date")
        # 退市当日及之后不再计入
        df = df.filter(
            pl.col("delist_date").is_null() | (pl.col(date_col) < pl.col("delist_date"))
        )

    if "in_universe" in df.columns:
        df = df.filter(pl.col("in_universe").fill_null(True))

    return df


def apply_announcement_lag(
    df: pl.DataFrame,
    fund_cols: list[str] | None = None,
) -> pl.DataFrame:
    """``trade_date < ann_date`` 时把基本面字段置空。"""
    if df.is_empty() or "ann_date" not in df.columns:
        return df
    df = df.clone()
    date_col = _date_col(df)
    df = _as_date_col(df, date_col)
    df = _as_date_col(df, "ann_date")
    cols = fund_cols
    if cols is None:
        cols = [c for c in df.columns if c in FUNDAMENTAL_COLUMNS]
    if not cols:
        return df
    hidden = pl.col("ann_date").is_not_null() & (pl.col(date_col) < pl.col("ann_date"))
    updates = [
        pl.when(hidden).then(pl.lit(None)).otherwise(pl.col(c)).alias(c) for c in cols
    ]
    return df.with_columns(updates)


def apply_point_in_time(df: pl.DataFrame) -> pl.DataFrame:
    """幸存者过滤 + 公告日滞后。没有可选列则原样返回。"""
    return apply_announcement_lag(apply_survivorship_filter(df))
