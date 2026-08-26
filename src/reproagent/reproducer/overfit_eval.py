"""从净值曲线跑 DSR / PBO / MinBTL / bootstrap / placebo。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


def placebo_pvalue_from_result(result: Any) -> float | None:
    if result is None:
        return None
    raw = getattr(result, "p_value", None)
    if raw is None and isinstance(result, dict):
        raw = result.get("p_value", result.get("pvalue"))
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _forward_returns_for_factor_panel(factor_values: Any) -> Any | None:
    if factor_values is None or "date" not in factor_values.columns:
        return None
    if "asset" not in factor_values.columns or factor_values["asset"].n_unique() < 2:
        return None
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.settings import get_settings

    dates = factor_values["date"].drop_nulls().to_list()
    parsed: list[date] = []
    for item in dates:
        if isinstance(item, date) and not isinstance(item, datetime):
            parsed.append(item)
        else:
            text = str(item)[:10]
            try:
                parsed.append(date.fromisoformat(text))
            except ValueError:
                continue
    if len(parsed) < 3:
        return None
    start, end = min(parsed), max(parsed)
    px = DataLoader(get_settings()).load_price_data("all", start, end)
    if px.is_empty() or "close" not in px.columns:
        return None
    date_col = "trade_date" if "trade_date" in px.columns else "date"
    asset_col = "ts_code" if "ts_code" in px.columns else "asset"
    px = px.sort([asset_col, date_col]).with_columns(
        (pl.col("close").shift(-1).over(asset_col) / pl.col("close") - 1).alias("forward_return")
    )
    return px.select(
        pl.col(date_col).alias("date"),
        pl.col(asset_col).alias("asset"),
        "forward_return",
    )


_EMPTY: dict[str, Any] = {
    "dsr": None,
    "dsr_pvalue": None,
    "dsr_deflated": None,
    "pbo": None,
    "pbo_overfit": None,
    "min_btl": None,
    "sharpe_ci": None,
    "placebo_pvalue": None,
    "walk_forward": None,
    "stress_test": None,
}


def evaluate_from_equity(equity_path: str | None) -> dict[str, Any]:
    """Read an equity-curve parquet and run DSR/PBO/MinBTL/bootstrap/placebo."""
    from reproagent.reproducer.anti_overfitting import (
        bootstrap_sharpe_ci,
        deflated_sharpe_ratio,
        min_backtest_length,
        placebo_test,
        prob_backtest_overfitting,
        subsample_stress_test,
        walk_forward_validation,
    )

    if not equity_path:
        return {**_EMPTY, "note": "No equity curve path"}

    path = Path(equity_path)
    if not path.exists():
        return {**_EMPTY, "note": f"Equity curve not found: {path}"}

    try:
        eq = pl.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        return {**_EMPTY, "note": f"Failed to read equity: {exc}"}

    ret_col: str | None = None
    for c in ("ls_return", "ls_return_raw", "long_short", "ls", "daily_return"):
        if c in eq.columns:
            ret_col = c
            break
    if ret_col is None:
        numeric = [
            c
            for c in eq.columns
            if c not in ("date", "trade_date", "group", "turnover", "asset")
            and eq.schema[c].is_numeric()
        ]
        if not numeric:
            return {**_EMPTY, "note": "No return columns in equity curve"}
        ret_col = str(numeric[0])

    series = eq[ret_col].drop_nulls().to_numpy()
    if len(series) < 5:
        return {**_EMPTY, "note": f"Too few observations: {len(series)}", "n_obs": len(series)}

    rets = series.astype(float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 5:
        return {**_EMPTY, "note": "Insufficient finite returns", "n_obs": len(rets)}

    sharpe = float(np.mean(rets) / (np.std(rets) + 1e-12) * np.sqrt(252))
    dsr = deflated_sharpe_ratio(sharpe, n_trials=10, n_obs=len(rets))
    pbo = prob_backtest_overfitting(rets, n_splits=min(5, max(2, len(rets) // 5)))
    min_btl = min_backtest_length(sharpe, variance=float(np.var(rets)))
    boot = bootstrap_sharpe_ci(rets, n_boot=200)

    placebo_p = None
    try:
        fv_path = path.parent / "factor_values.parquet"
        if fv_path.exists():
            fv = pl.read_parquet(fv_path)
            fwd = _forward_returns_for_factor_panel(fv)
            if fwd is not None:
                pr = placebo_test(fv, fwd, n_shuffles=50)
                placebo_p = placebo_pvalue_from_result(pr)
    except Exception:  # noqa: BLE001
        placebo_p = None

    out: dict[str, Any] = {
        "dsr": float(dsr.dsr),
        "dsr_pvalue": float(dsr.p_value),
        "dsr_deflated": bool(dsr.deflated),
        "pbo": float(pbo.pbo),
        "pbo_overfit": bool(pbo.overfit),
        "min_btl": int(min_btl.min_obs),
        "sharpe_ci": {
            "lower": float(boot.sharpe_ci_lower),
            "upper": float(boot.sharpe_ci_upper),
        },
        "placebo_pvalue": float(placebo_p) if placebo_p is not None else None,
        "walk_forward": None,
        "stress_test": None,
        "n_obs": len(rets),
        "sharpe": sharpe,
    }
    try:
        fv_path = path.parent / "factor_values.parquet"
        if fv_path.exists():
            fv = pl.read_parquet(fv_path)
            fwd = _forward_returns_for_factor_panel(fv)
            if fwd is not None:
                wf = walk_forward_validation(fv, fwd, n_splits=5)
                out["walk_forward"] = asdict(wf)
                merged = fv.join(fwd, on=["date", "asset"], how="inner").drop_nulls()
                if len(merged) >= 30:
                    st = subsample_stress_test(merged)
                    out["stress_test"] = asdict(st)
    except Exception:
        pass
    return out


def attach_anti_overfitting(result: Any) -> Any:
    """Fill BacktestResult DSR/PBO fields from the equity artifact."""
    path = getattr(result, "equity_curve_path", None)
    anti = evaluate_from_equity(str(path) if path is not None else None)
    ci = anti.get("sharpe_ci") or {}
    wf = anti.get("walk_forward") or {}
    oos = None
    if isinstance(wf, dict):
        oos = wf.get("oos_ic_mean")
    updates = {
        "dsr": anti.get("dsr"),
        "dsr_pvalue": anti.get("dsr_pvalue"),
        "pbo": anti.get("pbo"),
        "min_btl": anti.get("min_btl"),
        "sharpe_ci_lower": ci.get("lower") if isinstance(ci, dict) else None,
        "sharpe_ci_upper": ci.get("upper") if isinstance(ci, dict) else None,
        "walk_forward_ic_oos": oos,
        "placebo_pvalue": anti.get("placebo_pvalue"),
    }
    try:
        return result.model_copy(update=updates)
    except Exception:  # noqa: BLE001
        for k, v in updates.items():
            try:
                setattr(result, k, v)
            except Exception:  # noqa: BLE001
                pass
        return result
