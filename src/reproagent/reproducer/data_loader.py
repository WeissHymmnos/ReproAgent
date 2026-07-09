"""量价 / 基本面数据加载。"""

from __future__ import annotations

from datetime import date

import polars as pl

from reproagent.settings import Settings


class DataLoader:
    """从 ricequant / tushare / local 加载为 Polars DataFrame。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_price_data(
        self,
        universe: str,
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """日频量价：trade_date, ts_code, open, high, low, close, volume, amount。"""
        raise NotImplementedError("DataLoader.load_price_data")

    def load_fundamental_data(
        self,
        fields: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """基本面字段，如 roe_ttm, pe_ttm, turnover_rate。"""
        raise NotImplementedError("DataLoader.load_fundamental_data")
