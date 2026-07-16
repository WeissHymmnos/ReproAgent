"""Polars 因子计算引擎。"""

from __future__ import annotations

from datetime import date

import polars as pl

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import ReplicationConfig


class PolarsEngine:
    """实现 FactorEngine Protocol。用 Polars lazy API 计算因子。"""

    def __init__(self, config: ReplicationConfig) -> None:
        self.config = config

    def compute(
        self,
        factor_def: FactorDefinition,
        universe: str,
        start: date,
        end: date,
        data: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """返回 [date, asset, factor_value]。"""
        if data is None:
            from reproagent.reproducer.data_loader import DataLoader
            from reproagent.settings import Settings
            loader = DataLoader(Settings())
            data = loader.load_price_data(universe, start, end)
            
        formula = factor_def.formula
        
        if 'trade_date' not in data.columns and 'date' in data.columns:
            data = data.rename({'date': 'trade_date'})
        if 'ts_code' not in data.columns and 'asset' in data.columns:
            data = data.rename({'asset': 'ts_code'})
            
        if formula in data.columns:
            res = data.select(['trade_date', 'ts_code', pl.col(formula).alias('factor_value')])
        elif "close" in formula and "Ref" in formula:
            import re
            match = re.search(r'Ref\(close,\s*(\d+)\)', formula)
            n = int(match.group(1)) if match else 1
            res = data.sort(['ts_code', 'trade_date']).with_columns(
                (pl.col('close') / pl.col('close').shift(n).over('ts_code') - 1)
                .alias('factor_value')
            ).select(['trade_date', 'ts_code', 'factor_value'])
        else:
            res = data.select(['trade_date', 'ts_code', pl.col('close').alias('factor_value')])
            
        return res.rename({'trade_date': 'date', 'ts_code': 'asset'})
