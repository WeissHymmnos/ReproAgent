"""从价格面板算出最近交易日报价和涨跌统计。"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from reproagent.settings import Settings


def _date_col(df: pl.DataFrame) -> str:
    if "trade_date" in df.columns:
        return "trade_date"
    if "date" in df.columns:
        return "date"
    raise ValueError("price panel needs trade_date or date")


def _asset_col(df: pl.DataFrame) -> str:
    if "ts_code" in df.columns:
        return "ts_code"
    if "asset" in df.columns:
        return "asset"
    if "instrument" in df.columns:
        return "instrument"
    raise ValueError("price panel needs ts_code/asset")


def load_research_panel(
    settings: Settings,
    *,
    universe: str = "all",
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    """加载当前 DATA_SOURCE 在给定窗口内的价格面板。"""
    from reproagent.reproducer.data_loader import DataLoader

    loader = DataLoader(settings)
    start = start or date(1990, 1, 1)
    end = end or date.today()
    return loader.load_price_data(universe, start, end)


def last_session_quotes(
    panel: pl.DataFrame,
    *,
    limit: int | None = 50,
    spark_bars: int = 20,
) -> list[dict[str, Any]]:
    """每只标的一行：最近收盘、涨跌、短收盘序列。"""
    if panel.is_empty() or "close" not in panel.columns:
        return []
    dcol = _date_col(panel)
    acol = _asset_col(panel)
    df = panel.sort([acol, dcol])
    df = df.with_columns(
        pl.col("close").shift(1).over(acol).alias("_prev"),
        pl.col(dcol).max().over(acol).alias("_last_dt"),
    )
    last = df.filter(pl.col(dcol) == pl.col("_last_dt"))
    rows: list[dict[str, Any]] = []
    spark_n = max(2, int(spark_bars))
    hist = (
        df.group_by(acol)
        .agg(pl.col("close").tail(spark_n).alias("spark"))
        .to_dict(as_series=False)
    )
    sparks = dict(zip(hist[acol], hist["spark"], strict=True))
    for rec in last.to_dicts():
        close = rec.get("close")
        prev = rec.get("_prev")
        chg = None
        chg_pct = None
        try:
            c = float(close) if close is not None else None
            p = float(prev) if prev is not None else None
        except (TypeError, ValueError):
            c, p = None, None
        if c is not None and p is not None and abs(p) > 1e-12:
            chg = c - p
            chg_pct = chg / p
        spark = [float(x) for x in (sparks.get(rec[acol]) or []) if x is not None]
        session = rec.get(dcol)
        rows.append(
            {
                "asset": rec[acol],
                "session": str(session) if session is not None else None,
                "open": rec.get("open"),
                "high": rec.get("high"),
                "low": rec.get("low"),
                "close": c,
                "volume": rec.get("volume"),
                "amount": rec.get("amount"),
                "chg": chg,
                "chg_pct": chg_pct,
                "spark": spark,
            }
        )
    rows.sort(key=lambda r: abs(r["chg_pct"] or 0.0), reverse=True)
    if limit is not None and int(limit) > 0:
        rows = rows[: int(limit)]
    return rows


def pulse_from_quotes(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """上涨家数和涨跌幅极值。"""
    n = len(quotes)
    ups = sum(1 for q in quotes if (q.get("chg_pct") or 0) > 0)
    downs = sum(1 for q in quotes if (q.get("chg_pct") or 0) < 0)
    flats = n - ups - downs
    vols = [float(q["volume"]) for q in quotes if q.get("volume") is not None]
    vols.sort()
    median_vol = vols[len(vols) // 2] if vols else None
    signed = [q for q in quotes if q.get("chg_pct") is not None]
    gainer = max(signed, key=lambda q: q["chg_pct"]) if signed else None
    loser = min(signed, key=lambda q: q["chg_pct"]) if signed else None
    session = next((q.get("session") for q in quotes if q.get("session")), None)
    return {
        "session": session,
        "n_assets": n,
        "n_up": ups,
        "n_down": downs,
        "n_flat": flats,
        "median_volume": median_vol,
        "gainer": _mover(gainer),
        "loser": _mover(loser),
    }


def _mover(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "asset": row.get("asset"),
        "chg_pct": row.get("chg_pct"),
        "close": row.get("close"),
    }


def build_market_snapshot(
    settings: Settings,
    *,
    universe: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """当前数据源的报价和涨跌统计。"""
    panel = load_research_panel(settings, universe=universe)
    quotes = last_session_quotes(panel, limit=limit)
    return {
        "data_source": settings.data_source,
        "universe": universe,
        "rows": len(panel),
        "quotes": quotes,
        "pulse": pulse_from_quotes(quotes),
    }
