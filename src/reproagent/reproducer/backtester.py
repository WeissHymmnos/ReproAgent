"""分组回测 + IC。"""

from __future__ import annotations

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams
from reproagent.settings import Settings


class StrategyBacktester:
    """分组回测 + IC 计算。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        factor_values: pl.DataFrame,
        params: BacktestParams,
        factor_def: FactorDefinition,
        data: pl.DataFrame | None = None,
    ) -> BacktestResult:
        """分组收益、IC、夏普、回撤；落盘 parquet 后返回 BacktestResult。"""
        import uuid
        from datetime import datetime
        
        from reproagent.reproducer.metrics import (
            _as_float,
            compute_group_returns,
            compute_ic,
            compute_max_drawdown,
            compute_sharpe,
        )
        
        if data is None:
            from reproagent.reproducer.data_loader import DataLoader
            loader = DataLoader(self.settings)
            data = loader.load_price_data(factor_def.universe, params.start_date, params.end_date)
            
        if 'trade_date' not in data.columns and 'date' in data.columns:
            data = data.rename({'date': 'trade_date'})
        if 'ts_code' not in data.columns and 'asset' in data.columns:
            data = data.rename({'asset': 'ts_code'})
            
        data = data.sort(['ts_code', 'trade_date']).with_columns(
            (pl.col('close').shift(-1).over('ts_code') / pl.col('close') - 1)
            .alias('forward_return')
        )
        
        forward_returns = data.select([
            pl.col('trade_date').alias('date'),
            pl.col('ts_code').alias('asset'),
            'forward_return'
        ]).drop_nulls()
        
        ic_df = compute_ic(factor_values, forward_returns)
        ic_mean = _as_float(ic_df["ic"].mean()) if len(ic_df) > 0 else 0.0
        ic_std = _as_float(ic_df["ic"].std()) if len(ic_df) > 1 else 0.0
        ic_ir = ic_mean / ic_std if ic_std != 0 else 0.0
        
        num_groups = params.num_groups
        
        grouped = factor_values.drop_nulls('factor_value').with_columns(
            pl.col('factor_value').rank(method='ordinal').over('date').alias('rank')
        ).with_columns(
            (pl.col('rank') / (pl.col('rank').max().over('date') + 1) * num_groups)
            .cast(pl.Int32).alias('group')
        )
        
        group_returns = compute_group_returns(grouped, forward_returns, num_groups)
        
        df = grouped.join(forward_returns, on=['date', 'asset'], how='inner')
        daily_group_ret = df.group_by(['date', 'group']).agg(
            pl.col('forward_return').mean().alias('daily_return')
        )
        
        long_ret = daily_group_ret.filter(pl.col('group') == num_groups - 1).rename(
            {'daily_return': 'long_ret'}
        )
        short_ret = daily_group_ret.filter(pl.col('group') == 0).rename(
            {'daily_return': 'short_ret'}
        )
        
        ls_ret = long_ret.join(short_ret, on='date', how='inner').with_columns(
            (pl.col('long_ret') - pl.col('short_ret')).alias('ls_return_raw')
        ).sort('date')
        
        # --- Turnover & Transaction Costs ---
        # 1. 计算多空两端的权重
        long_weights = grouped.filter(pl.col('group') == num_groups - 1).with_columns(
            (pl.lit(1.0) / pl.len().over('date')).alias('weight')
        )
        short_weights = grouped.filter(pl.col('group') == 0).with_columns(
            (pl.lit(-1.0) / pl.len().over('date')).alias('weight')
        )
        weights = pl.concat([
            long_weights.select(['date', 'asset', 'weight']),
            short_weights.select(['date', 'asset', 'weight'])
        ])
        
        # 2. 计算调仓引发的权重变化 (w_t - w_{t-1})
        # 为每个 date 找到前一个 trade_date
        dates_df = weights.select('date').unique().sort('date').with_columns(
            pl.col('date').shift(1).alias('prev_date')
        )
        w_t = weights
        w_t_prev = weights.join(dates_df, left_on='date', right_on='prev_date').select([
            pl.col('date_right').alias('date'), # this is the current date
            'asset',
            pl.col('weight').alias('prev_weight')
        ])
        
        merged_w = w_t.join(
            w_t_prev, on=['date', 'asset'], how='full', coalesce=True
        ).fill_null(0.0)
        daily_turnover = merged_w.group_by('date').agg(
            (pl.col('weight') - pl.col('prev_weight')).abs().sum().alias('turnover')
        ).with_columns((pl.col('turnover') / 2.0).alias('turnover')) # 单边换手率
        
        avg_turnover = _as_float(daily_turnover["turnover"].mean())

        # 3. 扣减交易成本
        cost_rate = params.transaction_cost_bps / 10000.0
        ls_ret = ls_ret.join(daily_turnover, on="date", how="left").fill_null(0.0).with_columns(
            (pl.col("ls_return_raw") - pl.col("turnover") * cost_rate).alias("ls_return")
        )

        ls_series = ls_ret["ls_return"]

        sharpe = compute_sharpe(ls_series)
        equity_curve = (1 + ls_series).cum_prod()
        mdd = compute_max_drawdown(equity_curve)
        ann_return = (
            _as_float(ls_series.mean()) * 252 if len(ls_series) > 0 else 0.0
        )

        output_dir = self.settings.data_dir / "backtest" / factor_def.id
        output_dir.mkdir(parents=True, exist_ok=True)

        factor_values_path = output_dir / "factor_values.parquet"
        factor_values.write_parquet(factor_values_path)

        equity_curve_path = output_dir / "equity_curve.parquet"
        ls_ret.write_parquet(equity_curve_path)

        ic_path = output_dir / "ic.parquet"
        ic_df.write_parquet(ic_path)

        return BacktestResult(
            id=str(uuid.uuid4()),
            config_id="default",
            factor_id=factor_def.id,
            engine="polars",
            start_date=params.start_date,
            end_date=params.end_date,
            group_annualized_returns=group_returns,
            ic_mean=ic_mean,
            ic_ir=float(ic_ir),
            long_short_annual_return=ann_return,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            turnover=avg_turnover,
            factor_values_path=factor_values_path,
            equity_curve_path=equity_curve_path,
            computed_at=datetime.now(),
        )
