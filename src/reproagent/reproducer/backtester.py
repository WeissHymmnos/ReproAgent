"""分组回测 + IC。"""

from __future__ import annotations

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams
from reproagent.settings import Settings


def apply_min_hold_and_exit(
    panel: pl.DataFrame,
    *,
    min_holding_days: int = 1,
    exit_threshold: float | None = None,
) -> pl.DataFrame:
    """Carry the last non-zero signal for ``min_holding_days``; optional exit bound."""
    if panel.is_empty():
        return panel
    hold = max(1, int(min_holding_days or 1))
    if hold <= 1 and exit_threshold is None:
        return panel

    needed = {"date", "asset", "raw_weight"}
    missing = needed.difference(panel.columns)
    if missing:
        raise ValueError(f"apply_min_hold_and_exit missing columns: {sorted(missing)}")

    cols = ["date", "asset", "raw_weight"]
    if "factor_value" in panel.columns:
        cols.append("factor_value")
    rows = panel.sort(["asset", "date"]).select(cols).to_dicts()
    last_asset: object = None
    last_sig = 0.0
    days_held = 0
    out: list[dict] = []
    for raw in rows:
        r = dict(raw)
        asset = r["asset"]
        if asset != last_asset:
            last_asset = asset
            last_sig = 0.0
            days_held = 0
        sig = float(r["raw_weight"] or 0.0)
        fv = r.get("factor_value")
        if last_sig != 0.0:
            days_held += 1
            can_change = days_held >= hold
            want_exit = sig == 0.0 or (sig * last_sig < 0)
            if exit_threshold is not None and fv is not None:
                level = float(exit_threshold)
                if last_sig > 0 and float(fv) < level:
                    want_exit = True
                elif last_sig < 0 and float(fv) > -level:
                    want_exit = True
                elif last_sig > 0 and float(fv) >= level and sig == 0.0:
                    want_exit = False
                elif last_sig < 0 and float(fv) <= -level and sig == 0.0:
                    want_exit = False
            if not can_change:
                sig = last_sig
            elif not want_exit and sig == 0.0:
                sig = last_sig
        if sig != 0.0 and last_sig == 0.0:
            days_held = 1
        elif sig != 0.0 and sig * last_sig < 0:
            days_held = 1
        elif sig == 0.0:
            days_held = 0
        last_sig = sig
        r["raw_weight"] = sig
        out.append(r)
    return pl.DataFrame(out)


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

        run_dir = (
            self.settings.data_dir / "backtest" / f"{factor_def.id}-{uuid.uuid4().hex[:10]}"
        )

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

        if "trade_date" not in data.columns and "date" in data.columns:
            data = data.rename({"date": "trade_date"})
        if "ts_code" not in data.columns and "asset" in data.columns:
            data = data.rename({"asset": "ts_code"})

        data = data.sort(["ts_code", "trade_date"])
        _deduped = data.unique(subset=["trade_date", "ts_code"], keep="first").sort(
            ["ts_code", "trade_date"]
        )
        if _deduped.height != data.height:
            import logging

            logging.getLogger(__name__).warning(
                "Price panel had %d duplicated (trade_date, ts_code) rows; "
                "deduplicated before forward-return computation",
                data.height - _deduped.height,
            )
            data = _deduped
        data = data.with_columns(
            pl.when(pl.col("close").abs() > 1e-12)
            .then(pl.col("close").shift(-1).over("ts_code") / pl.col("close") - 1)
            .otherwise(None)
            .alias("forward_return")
        )

        forward_returns = data.select(
            [pl.col("trade_date").alias("date"), pl.col("ts_code").alias("asset"), "forward_return"]
        ).drop_nulls()

        fv_nn = factor_values.drop_nulls("factor_value")
        if fv_nn.height >= 2 and getattr(params, "mode", "factor") == "factor":
            import math

            from reproagent.exceptions import ReproductionError

            fv_std_raw = fv_nn["factor_value"].std()
            std_val = (
                float(fv_std_raw) if isinstance(fv_std_raw, (int, float)) else float("nan")
            )
            if not math.isfinite(std_val) or abs(std_val) < 1e-12:
                raise ReproductionError(
                    "Degenerate factor: zero cross-sectional variance in "
                    f"factor_value (std={std_val}) — cannot form groups; "
                    "refusing to fabricate long-short returns."
                )

        ic_df = compute_ic(factor_values, forward_returns)
        if len(ic_df) > 0:
            ic_mean = _as_float(ic_df["ic"].mean())
            ic_std = _as_float(ic_df["ic"].std()) if len(ic_df) > 1 else 0.0
            ic_ir = ic_mean / ic_std if ic_std != 0 else 0.0
        else:
            ic_mean = 0.0
            ic_ir = 0.0

        num_groups = params.num_groups

        mode = getattr(params, "mode", "factor")
        group_returns = {}
        
        if mode == "factor":
            n_assets = 0
            if "asset" in factor_values.columns and factor_values.height:
                n_assets = int(factor_values.select(pl.col("asset").n_unique()).item() or 0)
            # 2-stock local panels cannot fill quintiles: long/short join would be empty.
            effective_groups = (
                int(num_groups) if n_assets >= int(num_groups or 0) else max(2, n_assets or 2)
            )
            grouped = (
                factor_values.drop_nulls("factor_value")
                .with_columns(pl.col("factor_value").rank(method="ordinal").over("date").alias("rank"))
                .with_columns(
                    (pl.col("rank") / (pl.col("rank").max().over("date") + 1) * effective_groups)
                    .cast(pl.Int32)
                    .alias("group")
                )
            )

            group_returns = compute_group_returns(grouped, forward_returns, effective_groups)

            df = grouped.join(forward_returns, on=["date", "asset"], how="inner")
            daily_group_ret = df.group_by(["date", "group"]).agg(
                pl.col("forward_return").mean().alias("daily_return")
            )

            long_ret = daily_group_ret.filter(pl.col("group") == effective_groups - 1).rename(
                {"daily_return": "long_ret"}
            )
            short_ret = daily_group_ret.filter(pl.col("group") == 0).rename(
                {"daily_return": "short_ret"}
            )

            ls_ret = (
                long_ret.join(short_ret, on="date", how="inner")
                .with_columns((pl.col("long_ret") - pl.col("short_ret")).alias("ls_return_raw"))
                .sort("date")
            )

            # --- Turnover & Transaction Costs ---
            # 1. 计算多空两端的权重
            long_weights = grouped.filter(pl.col("group") == effective_groups - 1).with_columns(
                (pl.lit(1.0) / pl.len().over("date")).alias("weight")
            )
            short_weights = grouped.filter(pl.col("group") == 0).with_columns(
                (pl.lit(-1.0) / pl.len().over("date")).alias("weight")
            )
            weights = pl.concat(
                [
                    long_weights.select(["date", "asset", "weight"]),
                    short_weights.select(["date", "asset", "weight"]),
                ]
            )
        else:
            df_weights = factor_values.drop_nulls("factor_value")
            df_weights = df_weights.with_columns(
                pl.col("factor_value")
                .rank(method="ordinal", descending=False)
                .over("date")
                .alias("rank_asc"),
                pl.col("factor_value")
                .rank(method="ordinal", descending=True)
                .over("date")
                .alias("rank_desc"),
            )

            direction = params.direction or "long_short"
            rule = params.selection_rule or "top_bottom_n"
            top_n = params.top_n or 10
            bottom_n = params.bottom_n or 10

            if rule in {"top_n", "bottom_n", "top_bottom_n"}:
                if rule == "top_n":
                    df_weights = df_weights.with_columns(
                        pl.when(pl.col("rank_desc") <= top_n)
                        .then(pl.lit(1.0))
                        .otherwise(pl.lit(0.0))
                        .alias("raw_weight")
                    )
                elif rule == "bottom_n":
                    sign = -1.0 if direction == "long_short" else 1.0
                    df_weights = df_weights.with_columns(
                        pl.when(pl.col("rank_asc") <= bottom_n)
                        .then(pl.lit(sign))
                        .otherwise(pl.lit(0.0))
                        .alias("raw_weight")
                    )
                else:
                    df_weights = df_weights.with_columns(
                        pl.when(pl.col("rank_desc") <= top_n)
                        .then(pl.lit(1.0))
                        .when(pl.col("rank_asc") <= bottom_n)
                        .then(pl.lit(-1.0))
                        .otherwise(pl.lit(0.0))
                        .alias("raw_weight")
                    )
            else:
                long_th = params.long_threshold
                short_th = params.short_threshold
                if long_th is None and short_th is None:
                    raise ValueError(
                        "selection_rule='threshold' requires long_threshold "
                        "and/or short_threshold"
                    )
                df_weights = df_weights.with_columns(pl.lit(0.0).alias("raw_weight"))
                if long_th is not None:
                    df_weights = df_weights.with_columns(
                        pl.when(pl.col("factor_value") >= long_th)
                        .then(pl.lit(1.0))
                        .otherwise(pl.col("raw_weight"))
                        .alias("raw_weight")
                    )
                if short_th is not None and direction == "long_short":
                    df_weights = df_weights.with_columns(
                        pl.when(pl.col("factor_value") <= short_th)
                        .then(pl.lit(-1.0))
                        .otherwise(pl.col("raw_weight"))
                        .alias("raw_weight")
                    )

            if direction in {"long_only", "long_flat"}:
                df_weights = df_weights.with_columns(
                    pl.when(pl.col("raw_weight") < 0)
                    .then(0.0)
                    .otherwise(pl.col("raw_weight"))
                    .alias("raw_weight")
                )

            df_weights = apply_min_hold_and_exit(
                df_weights,
                min_holding_days=int(params.min_holding_days or 1),
                exit_threshold=params.exit_threshold,
            )
            df_weights = df_weights.filter(pl.col("raw_weight") != 0.0)
            if not df_weights.is_empty():
                weights = df_weights.with_columns(
                    (
                        pl.col("raw_weight")
                        / pl.len().over(["date", pl.col("raw_weight") > 0])
                    ).alias("weight")
                ).select(["date", "asset", "weight"])
            else:
                weights = pl.DataFrame(
                    {"date": [], "asset": [], "weight": []},
                    schema={"date": pl.Date, "asset": pl.Utf8, "weight": pl.Float64},
                )

            cap = params.max_weight_per_position
            if cap is not None and float(cap) > 0 and not weights.is_empty():
                weights = weights.with_columns(
                    pl.col("weight").clip(-float(cap), float(cap)).alias("weight")
                )
            npos = params.max_positions
            if npos is not None and int(npos) > 0 and not weights.is_empty():
                weights = (
                    weights.with_columns(
                        pl.col("weight")
                        .abs()
                        .rank(method="ordinal", descending=True)
                        .over("date")
                        .alias("_rk")
                    )
                    .filter(pl.col("_rk") <= int(npos))
                    .drop("_rk")
                )

            merged = weights.join(forward_returns, on=["date", "asset"], how="inner")
            if not merged.is_empty():
                ls_ret = merged.group_by("date").agg(
                    (pl.col("weight") * pl.col("forward_return")).sum().alias("ls_return_raw")
                ).sort("date")
            else:
                ls_ret = pl.DataFrame(
                    {"date": forward_returns["date"].unique().sort(), "ls_return_raw": 0.0}
                )

        # 2. 计算调仓引发的权重变化 (w_t - w_{t-1})
        if weights.is_empty() or ls_ret.is_empty():
            empty_ls = ls_ret if not ls_ret.is_empty() else pl.DataFrame(
                {"date": [], "ls_return_raw": [], "ls_return": []},
                schema={"date": pl.Date, "ls_return_raw": pl.Float64, "ls_return": pl.Float64},
            )
            if "ls_return" not in empty_ls.columns:
                empty_ls = empty_ls.with_columns(pl.col("ls_return_raw").alias("ls_return"))
            ls_ret = empty_ls
            avg_turnover = 0.0
            ls_series = (
                ls_ret["ls_return"]
                if "ls_return" in ls_ret.columns
                else pl.Series("ls_return", [], dtype=pl.Float64)
            )
            sharpe = compute_sharpe(ls_series)
            equity_curve = (1 + ls_series).cum_prod() if ls_series.len() else ls_series
            mdd = compute_max_drawdown(equity_curve) if ls_series.len() else 0.0
            ann_return = _as_float(ls_series.mean()) * 252 if ls_series.len() else 0.0
            output_dir = run_dir
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
                group_annualized_returns=group_returns if isinstance(group_returns, dict) else {},
                ic_mean=ic_mean,
                ic_ir=ic_ir,
                long_short_annual_return=ann_return,
                sharpe_ratio=sharpe,
                max_drawdown=mdd,
                turnover=avg_turnover,
                factor_values_path=factor_values_path,
                equity_curve_path=equity_curve_path,
                computed_at=datetime.now(),
            )

        # 为每个 date 找到前一个 trade_date
        dates_df = (
            weights.select("date")
            .unique()
            .sort("date")
            .with_columns(pl.col("date").shift(1).alias("prev_date"))
        )
        w_t = weights
        w_t_prev = weights.join(dates_df, left_on="date", right_on="prev_date").select(
            [
                pl.col("date_right").alias("date"),  # this is the current date
                "asset",
                pl.col("weight").alias("prev_weight"),
            ]
        )

        merged_w = w_t.join(w_t_prev, on=["date", "asset"], how="full", coalesce=True).fill_null(
            0.0
        )
        daily_turnover = (
            merged_w.group_by("date")
            .agg((pl.col("weight") - pl.col("prev_weight")).abs().sum().alias("turnover"))
            .with_columns((pl.col("turnover") / 2.0).alias("turnover"))
        )  # 单边换手率

        avg_turnover = _as_float(daily_turnover["turnover"].mean())

        # 3. 扣减交易成本
        cost_rate = params.transaction_cost_bps / 10000.0
        ls_ret = (
            ls_ret.join(daily_turnover, on="date", how="left")
            .fill_null(0.0)
            .with_columns(
                (pl.col("ls_return_raw") - pl.col("turnover") * cost_rate).alias("ls_return")
            )
        )

        ls_series = ls_ret["ls_return"]

        sharpe = compute_sharpe(ls_series)
        equity_curve = (1 + ls_series).cum_prod()
        mdd = compute_max_drawdown(equity_curve)
        ann_return = _as_float(ls_series.mean()) * 252 if len(ls_series) > 0 else 0.0

        output_dir = run_dir
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


def neutralize_industry(
    factor: pl.Series,
    industry: pl.Series,
) -> pl.Series:
    """截面回归残差法：factor ~ industry_dummies → residuals。"""
    df = pl.DataFrame({"factor": factor, "industry": industry}).drop_nulls()
    if df.is_empty():
        return factor
    industry_means = df.group_by("industry").agg(pl.col("factor").mean().alias("ind_mean"))
    df = df.join(industry_means, on="industry", how="left")
    return df["factor"] - df["ind_mean"]


def neutralize_market_cap(
    factor: pl.Series,
    log_mcap: pl.Series,
) -> pl.Series:
    """截面回归残差法：factor ~ log_mcap → residuals。"""
    df = pl.DataFrame({"factor": factor, "log_mcap": log_mcap}).drop_nulls()
    if df.is_empty() or df["log_mcap"].std() == 0:
        return factor
    # OLS: factor = α + β * log_mcap + ε
    x = df["log_mcap"].to_numpy()
    y = df["factor"].to_numpy()
    import numpy as np

    x_with_intercept = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(x_with_intercept, y, rcond=None)[0]
    residuals = y - x_with_intercept @ beta
    return pl.Series("neutral_factor", residuals)
