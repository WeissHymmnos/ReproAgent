from __future__ import annotations

from pathlib import Path

import polars as pl


def test_sample_report_path(sample_report_path: Path) -> None:
    assert sample_report_path.exists()
    assert sample_report_path.suffix == ".pdf"
    assert sample_report_path.stat().st_size > 100


def test_prices_parquet_path(prices_parquet_path: Path) -> None:
    assert prices_parquet_path.exists()
    assert prices_parquet_path.suffix == ".parquet"
    df = pl.read_parquet(prices_parquet_path)
    assert len(df) >= 60
    assert "datetime" in df.columns
    assert "trade_date" in df.columns
    assert "instrument" in df.columns
    assert "ts_code" in df.columns
    assert "open" in df.columns
    assert "high" in df.columns
    assert "low" in df.columns
    assert "close" in df.columns
    assert "volume" in df.columns
    assert "amount" in df.columns
