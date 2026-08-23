"""指标提取与图表生成。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl

from reproagent.models.backtest import BacktestResult


def kendall_tau_pairs(x: Any, y: Any) -> float:
    """Kendall tau; scipy if present, otherwise a pairwise numpy-free fallback."""
    xs = list(x)
    ys = list(y)
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    try:
        from scipy.stats import kendalltau

        tau, _ = kendalltau(xs[:n], ys[:n])
        if tau is None:
            return 0.0
        import math

        val = float(tau)
        return 0.0 if math.isnan(val) else val
    except ImportError:
        pass
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            sx = int(bool(xs[i] > xs[j])) - int(bool(xs[i] < xs[j]))
            sy = int(bool(ys[i] > ys[j])) - int(bool(ys[i] < ys[j]))
            if sx == 0 or sy == 0:
                continue
            if sx == sy:
                conc += 1
            else:
                disc += 1
    tot = conc + disc
    return (conc - disc) / tot if tot else 0.0


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce polars scalar aggregates to float for typing and safety.

    NaN/Inf → default，避免 ic_mean=nan 把健康复现打成 unhealthy。
    """
    import math

    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def compute_ic(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
) -> pl.DataFrame:
    """截面 rank IC（按日期），返回 [date, ic]（丢弃单日 nan corr）。"""
    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()
    ic_df = (
        df.group_by("date")
        .agg(pl.corr("factor_value", "forward_return", method="spearman").alias("ic"))
        .sort("date")
    )
    # 全日因子常数 / 样本过少时 spearman 为 null/nan，不参与均值
    if "ic" in ic_df.columns:
        ic_df = ic_df.filter(pl.col("ic").is_not_null() & pl.col("ic").is_finite())
    return ic_df


def compute_group_returns(
    grouped: pl.DataFrame,
    returns: pl.DataFrame,
    num_groups: int,
) -> dict[int, float]:
    """计算各分组年化收益。"""
    df = grouped.join(returns, on=["date", "asset"], how="inner")
    daily_group_ret = df.group_by(["date", "group"]).agg(
        pl.col("forward_return").mean().alias("daily_return")
    )
    ann_ret = (
        daily_group_ret.group_by("group")
        .agg((pl.col("daily_return").mean() * 252).alias("ann_return"))
        .sort("group")
    )
    return dict(zip(ann_ret["group"].to_list(), ann_ret["ann_return"].to_list()))


def compute_sharpe(returns: pl.Series, freq: str = "daily") -> float:
    """夏普比率；日频年化因子 √252。"""
    if len(returns) == 0:
        return 0.0
    std = _as_float(returns.std())
    mean = _as_float(returns.mean())
    if std == 0.0:
        return 0.0
    ann_factor = 252**0.5 if freq == "daily" else 1.0
    return (mean / std) * ann_factor


def compute_max_drawdown(equity_curve: pl.Series) -> float:
    """最大回撤。"""
    if len(equity_curve) == 0:
        return 0.0
    cum_max = equity_curve.cum_max()
    drawdown = (equity_curve - cum_max) / cum_max
    return abs(_as_float(drawdown.min()))


def generate_charts(
    backtest_result: BacktestResult,
    output_dir: Path,
) -> list[Path]:
    """生成净值曲线、分组收益、IC 时序图，返回图片路径。"""
    from reproagent.utils.plotting import (
        save_equity_curve_chart,
        save_group_returns_chart,
        save_ic_timeseries_chart,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    if backtest_result.group_annualized_returns:
        p = save_group_returns_chart(
            backtest_result.group_annualized_returns, output_dir / "group_returns.png"
        )
        paths.append(p)

    if backtest_result.equity_curve_path.exists():
        df = pl.read_parquet(backtest_result.equity_curve_path)
        if "date" in df.columns and "ls_return" in df.columns:
            equity = (1 + df["ls_return"]).cum_prod()
            equity_dict = dict(zip(df["date"].to_list(), equity.to_list()))
            p = save_equity_curve_chart(equity_dict, output_dir / "equity_curve.png")
            paths.append(p)

    factor_values_dir = backtest_result.factor_values_path.parent
    ic_path = factor_values_dir / "ic.parquet"
    if ic_path.exists():
        df = pl.read_parquet(ic_path)
        if "date" in df.columns and "ic" in df.columns:
            ic_dict = dict(zip(df["date"].to_list(), df["ic"].to_list()))
            p = save_ic_timeseries_chart(ic_dict, output_dir / "ic_timeseries.png")
            paths.append(p)

    return paths


def metrics_from_backtest(result: Any) -> dict[str, Any]:
    """Flat dashboard metrics + optional equity series from a BacktestResult."""
    import math

    def _finite(name: str, default: float = 0.0) -> float:
        raw = getattr(result, name, default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(val):
            return default
        return val

    ic_series: list[float] = []
    excess_cum: list[float] = []
    path = getattr(result, "equity_curve_path", None)
    daily = serialize_equity_returns(path) if path is not None else {}
    if daily:
        acc = 1.0
        for key in sorted(daily):
            r = float(daily[key])
            ic_series.append(r)
            acc *= 1.0 + r
            excess_cum.append(acc - 1.0)
    return {
        "ic": _finite("ic_mean"),
        "icir": _finite("ic_ir"),
        "ann_return": _finite("long_short_annual_return"),
        "max_drawdown": _finite("max_drawdown"),
        "sharpe": _finite("sharpe_ratio"),
        "turnover": _finite("turnover"),
        "ic_series": ic_series,
        "excess_cum": excess_cum,
    }


def metrics_from_artifact_dir(dir_path: Path) -> dict[str, Any]:
    """Rebuild dashboard metrics from a ``backtest/<id>/`` parquet folder."""
    from types import SimpleNamespace

    folder = Path(dir_path)
    ic_mean = 0.0
    ic_ir = 0.0
    icp = folder / "ic.parquet"
    if icp.exists():
        df = pl.read_parquet(icp)
        if "ic" in df.columns:
            series = df["ic"].drop_nulls()
            if series.len():
                ic_mean = _as_float(series.mean())
                std = _as_float(series.std()) if series.len() > 1 else 0.0
                ic_ir = ic_mean / std if std else 0.0
    sharpe = 0.0
    mdd = 0.0
    ann = 0.0
    equity = folder / "equity_curve.parquet"
    if equity.exists():
        eq = pl.read_parquet(equity)
        col = next(
            (c for c in ("ls_return", "ls_return_raw", "long_short") if c in eq.columns),
            None,
        )
        if col:
            ls = eq[col].drop_nulls()
            if ls.len():
                sharpe = compute_sharpe(ls)
                curve = (1 + ls).cum_prod()
                mdd = compute_max_drawdown(curve)
                ann = _as_float(ls.mean()) * 252
    proxy = SimpleNamespace(
        ic_mean=ic_mean,
        ic_ir=ic_ir,
        long_short_annual_return=ann,
        max_drawdown=mdd,
        sharpe_ratio=sharpe,
        turnover=0.0,
        equity_curve_path=equity if equity.exists() else None,
    )
    return metrics_from_backtest(proxy)


_GENERIC_ARTIFACT_KEY = re.compile(
    r"^(?:factor(?:[_-]?\d+)?|f\d{1,4})$",
    re.IGNORECASE,
)


def _is_generic_artifact_key(name: str) -> bool:
    """Extractor placeholders like factor_6 / F001 collide across reports."""
    s = (name or "").strip()
    return (not s) or len(s) < 3 or bool(_GENERIC_ARTIFACT_KEY.match(s))


def _artifact_keys_for_entry(entry: Any) -> set[str]:
    """Stable names for matching ``backtest/<key>`` folders (lowercased)."""
    from reproagent.library.wiki_writer import safe_factor_filename

    factor = getattr(entry, "factor", None)
    raw: list[Any] = [
        getattr(factor, "name", None),
        getattr(factor, "name_cn", None),
        getattr(entry, "id", None),
        getattr(entry, "backtest_result_id", None),
    ]
    fid = getattr(factor, "id", None)
    if fid and not _is_generic_artifact_key(str(fid)):
        raw.append(fid)
    keys: set[str] = set()
    for item in raw:
        text = str(item).strip() if item else ""
        if _is_generic_artifact_key(text):
            continue
        keys.add(text.lower())
        safe = safe_factor_filename(text)
        if not _is_generic_artifact_key(safe):
            keys.add(safe.lower())
    return keys


def _artifact_dir_has_rows(path: Path) -> bool:
    """True when equity/ic parquet exists and has at least one row."""
    for fname in ("equity_curve.parquet", "ic.parquet"):
        fp = path / fname
        if not fp.is_file():
            continue
        try:
            df = pl.read_parquet(fp)
        except Exception:  # noqa: BLE001
            continue
        if df.height > 0:
            return True
    return False


def find_backtest_artifact_dir(data_dir: Path, entry: Any) -> Path | None:
    """Newest ``backtest/<name|id>/`` dir matching a library entry.

    Matching is case-insensitive. Generic extractor ids (``factor_6``, ``F1``)
    are ignored so they cannot steal another factor's folder. Empty parquet
    dirs are skipped.
    """
    root = Path(data_dir) / "backtest"
    if not root.is_dir():
        return None
    names = _artifact_keys_for_entry(entry)
    if not names:
        return None
    hits: list[Path] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        folder = path.name.lower()
        if folder in names or any(folder.startswith(n + "-") for n in names):
            if _artifact_dir_has_rows(path):
                hits.append(path)
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


def serialize_equity_returns(path: Path | None) -> dict[str, float]:
    """Daily long-short returns from equity_curve.parquet (`date` + `ls_return`)."""
    if path is None or not Path(path).exists():
        return {}
    df = pl.read_parquet(path)
    if "date" not in df.columns or "ls_return" not in df.columns:
        return {}
    out: dict[str, float] = {}
    for d, r in zip(df["date"].to_list(), df["ls_return"].to_list()):
        if r is None:
            continue
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        out[key] = float(r)
    return out


def compute_alpha_decay(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
    lags: list[int] | None = None,
) -> dict[int, float]:
    """前向多滞后期 Rank IC 衰减曲线。

    对每个 lag，用 factor_value(t) 预测 forward_return(t+lag)，
    计算截面的平均 Rank IC。

    Returns
    -------
    dict[int, float]: {lag_days: mean_rank_ic}
    """
    if lags is None:
        lags = [1, 2, 3, 5, 10, 20]

    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()
    df = df.sort(["asset", "date"])

    result: dict[int, float] = {}
    for lag in lags:
        lagged = df.with_columns(
            pl.col("forward_return").shift(-lag).over("asset").alias(f"fwd_lag{lag}")
        ).drop_nulls(f"fwd_lag{lag}")

        if lagged.is_empty():
            result[lag] = 0.0
            continue

        ic_df = (
            lagged.group_by("date")
            .agg(pl.corr("factor_value", f"fwd_lag{lag}", method="spearman").alias("ic"))
            .drop_nulls("ic")
        )
        result[lag] = _as_float(ic_df["ic"].mean()) if len(ic_df) > 0 else 0.0

    return result


def compute_monotonicity(
    grouped_returns: pl.DataFrame,
) -> float:
    """分组收益单调性：Kendall tau between (group_rank, group_mean_return) per date。

    Parameters
    ----------
    grouped_returns: 含 date, group (int), daily_return 列

    Returns
    -------
    float: 逐日 Kendall tau 的截面均值（无偏见 0）
    """
    if grouped_returns.is_empty():
        return 0.0

    if "group" not in grouped_returns.columns or "daily_return" not in grouped_returns.columns:
        return 0.0

    dates = grouped_returns["date"].unique().to_list()
    taus: list[float] = []
    for d in dates:
        ddf = grouped_returns.filter(pl.col("date") == d)
        if len(ddf) < 2:
            continue
        tau = kendall_tau_pairs(ddf["group"].to_list(), ddf["daily_return"].to_list())
        taus.append(tau)

    return float(sum(taus) / len(taus)) if taus else 0.0


def compute_half_life(ic_series: dict[int, float]) -> float:
    """从 alpha decay 曲线估算因子半衰期（Rank IC 衰减到初始值一半的天数）。

    使用指数衰减拟合：IC(lag) ≈ IC₀ * exp(-lag / τ)
    """
    if not ic_series:
        return 0.0

    import numpy as np

    lags = sorted(ic_series.keys())
    ic_values = [ic_series[lag] for lag in lags]
    ic0 = abs(ic_values[0]) if ic_values[0] != 0 else 1.0

    # 找第一个 |IC| < |IC₀|/2 的 lag
    half_threshold = ic0 / 2.0
    for lag, ic in zip(lags, ic_values):
        if abs(ic) < half_threshold:
            return float(lag)

    # 如果未衰减到一半，做指数拟合估算
    if len(lags) >= 2:
        log_values = [np.log(max(abs(v), 1e-10)) for v in ic_values]
        if len(set(lags)) >= 2:
            slope, _ = np.polyfit(lags, log_values, 1)
            if abs(slope) > 1e-10:
                return float(-np.log(2) / slope)

    return float(len(lags))
