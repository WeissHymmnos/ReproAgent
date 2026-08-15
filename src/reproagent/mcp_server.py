"""FastMCP 服务器：暴露 reproagent 能力为 MCP 工具。

供 Claude Code / Claude Desktop 通过 MCP 协议调用。
启动方式: uv run reproagent mcp
"""

from __future__ import annotations


def _score_from_metrics(
    *,
    ic_mean: float,
    sharpe: float,
    dsr: float | None,
    pbo: float | None,
    max_drawdown: float,
) -> dict:
    """Map core metrics onto a 0–100 score and A/B/C/D grade."""
    score = 50.0
    score += max(-20.0, min(20.0, ic_mean * 200.0))
    score += max(-15.0, min(20.0, sharpe * 10.0))
    score -= max(0.0, min(15.0, abs(max_drawdown) * 30.0))
    if dsr is not None:
        score += max(-10.0, min(15.0, (dsr - 0.5) * 20.0))
    if pbo is not None:
        score -= max(0.0, min(20.0, pbo * 25.0))
    score = max(0.0, min(100.0, score))
    if score >= 80:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 50:
        grade = "C"
    else:
        grade = "D"
    return {"score": round(score, 1), "grade": grade}


def _run_library_backtest(expression: str) -> dict:
    """Run the shipped backtester without FastMCP."""
    from datetime import UTC, date, datetime

    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.replication import BacktestParams, ReplicationConfig
    from reproagent.reproducer.backtester import StrategyBacktester
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.reproducer.polars_engine import PolarsEngine
    from reproagent.settings import Settings, get_settings

    base = get_settings()
    settings = Settings(
        _env_file=None,
        app_env="dev",
        data_source="local",
        local_data_path=base.local_data_path,
        data_dir=base.data_dir,
        allow_mock_llm=True,
        parser_backend="finpdfpro",
    )
    loader = DataLoader(settings)
    start = date.fromisoformat("2023-01-02")
    end = date.fromisoformat("2023-02-10")
    fdef = FactorDefinition(
        id="library-grade",
        spec_id="library-grade",
        name="library_grade",
        name_cn="库评分",
        style="other",
        formula=expression,
        input_fields=[],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    data = loader.load_price_data("local_panel", start, end)
    cfg = ReplicationConfig(
        id="library-grade",
        report_id="library-grade",
        factor_specs=[],
        engine="polars",
        data_source=settings.data_source,  # type: ignore[arg-type]
        backtest_params=BacktestParams(start_date=start, end_date=end, transaction_cost_bps=0.0),
        parser_version=settings.parser_version,
        extraction_model_id="library-grade",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(cfg, allow_formula_fallback=False)
    fv = engine.compute(fdef, "local_panel", start, end, data=data)
    bt = StrategyBacktester(settings).run(
        factor_values=fv,
        params=BacktestParams(
            start_date=start,
            end_date=end,
            num_groups=5,
            transaction_cost_bps=0.0,
        ),
        factor_def=fdef,
        data=data,
    )
    return {
        "backtest_id": bt.id,
        "rows": len(fv),
        "ic_mean": bt.ic_mean,
        "sharpe_ratio": bt.sharpe_ratio,
        "max_drawdown": bt.max_drawdown,
        "equity_curve_path": str(bt.equity_curve_path),
    }


def _anti_from_equity(equity_path: str | None) -> dict:
    empty = {"dsr": None, "pbo": None}
    if not equity_path:
        return empty
    from pathlib import Path

    path = Path(equity_path)
    if not path.exists():
        return empty
    try:
        import polars as pl

        from reproagent.reproducer.anti_overfitting import (
            deflated_sharpe_ratio,
            prob_backtest_overfitting,
        )

        eq = pl.read_parquet(path)
        col = "long_short" if "long_short" in eq.columns else None
        if col is None:
            for name in eq.columns:
                if "return" in name.lower() or "ls" in name.lower():
                    col = name
                    break
        if col is None:
            return empty
        rets = [float(v) for v in eq[col].drop_nulls().to_list() if v is not None]
        if len(rets) < 5:
            return empty
        return {
            "dsr": float(deflated_sharpe_ratio(rets)),
            "pbo": float(prob_backtest_overfitting(rets)),
        }
    except Exception:  # noqa: BLE001
        return empty


def library_grade_impl(expression: str | None, backtest_id: str | None = None) -> dict:
    """Module-level 0-100 grade used by FastMCP and finaince.tools (no FastMCP import)."""
    if not expression and not backtest_id:
        return {
            "score": 0,
            "grade": "D",
            "error": "Provide expression and/or backtest_id",
            "scorer": "library_grade",
        }
    if not expression:
        return {
            "score": 0,
            "grade": "C",
            "note": "backtest_id-only lookup is limited; pass expression for full score",
            "backtest_id": backtest_id,
            "scorer": "library_grade",
        }
    try:
        bt = _run_library_backtest(expression)
    except Exception as exc:  # noqa: BLE001
        return {
            "score": 0,
            "grade": "D",
            "error": str(exc),
            "scorer": "library_grade",
        }
    anti = _anti_from_equity(bt.get("equity_curve_path"))
    metrics = _score_from_metrics(
        ic_mean=float(bt.get("ic_mean") or 0.0),
        sharpe=float(bt.get("sharpe_ratio") or 0.0),
        dsr=anti.get("dsr"),
        pbo=anti.get("pbo"),
        max_drawdown=float(bt.get("max_drawdown") or 0.0),
    )
    return {
        **metrics,
        "backtest_id": bt.get("backtest_id"),
        "components": {
            "ic_mean": bt.get("ic_mean"),
            "sharpe_ratio": bt.get("sharpe_ratio"),
            "max_drawdown": bt.get("max_drawdown"),
            "dsr": anti.get("dsr"),
            "pbo": anti.get("pbo"),
        },
        "scorer": "library_grade",
    }


def build_mcp_server() -> object:
    """构建并返回 MCP 服务器实例（FastMCP）。

    8 个工具：
    - validate_expression: 校验因子表达式
    - list_operators: 列出所有算子
    - run_backtest: 运行因子回测
    - score_factor: 多维度评分
    - diagnose_factor: 失败模式诊断
    - run_anti_overfitting: 反过拟合检验
    - list_universes: 列出股票池
    - search_factor_library: 搜索因子库
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError("FastMCP is required for MCP server. Install with: pip install fastmcp")

    mcp = FastMCP("reproagent")

    @mcp.tool()
    def validate_expression(expression: str) -> dict:
        """校验因子表达式的语法、算子和字段白名单合规性。"""
        from reproagent.reproducer.polars_engine import validate_expression as _validate

        return _validate(expression)

    @mcp.tool()
    def list_operators() -> list[dict]:
        """返回所有支持的算子及其签名。"""
        from reproagent.reproducer.polars_engine import _CONTEXT

        return [
            {"name": name, "type": type(func).__name__}
            for name, func in sorted(_CONTEXT.items())
            if name not in ("pl", "Const")
        ]

    @mcp.tool()
    def run_backtest(
        expression: str,
        start_date: str = "2023-01-02",
        end_date: str = "2023-02-10",
        universe: str = "csi300",
        num_groups: int = 5,
    ) -> dict:
        """运行完整因子回测（计算因子值 + 简易评分指标）。"""
        from datetime import UTC, date, datetime

        from reproagent.models.factor_def import FactorDefinition
        from reproagent.models.replication import BacktestParams, ReplicationConfig
        from reproagent.reproducer.backtester import StrategyBacktester
        from reproagent.reproducer.data_loader import DataLoader
        from reproagent.reproducer.polars_engine import PolarsEngine
        from reproagent.settings import get_settings

        settings = get_settings()
        loader = DataLoader(settings)
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        fdef = FactorDefinition(
            id="mcp-backtest",
            spec_id="mcp",
            name="mcp_factor",
            name_cn="MCP因子",
            style="other",
            formula=expression,
            input_fields=[],
            universe=universe,
            rebalance_frequency="monthly",
        )

        data = loader.load_price_data(universe, start, end)
        cfg = ReplicationConfig(
            id="mcp",
            report_id="mcp",
            factor_specs=[],
            engine="polars",
            data_source=settings.data_source,  # type: ignore[arg-type]
            backtest_params=BacktestParams(start_date=start, end_date=end),
            parser_version=settings.parser_version,
            extraction_model_id="mcp",
            created_at=datetime.now(UTC),
        )
        engine = PolarsEngine(cfg, allow_formula_fallback=False)
        fv = engine.compute(fdef, universe, start, end, data=data)
        bt = StrategyBacktester(settings).run(
            factor_values=fv,
            params=BacktestParams(
                start_date=start, end_date=end, num_groups=num_groups
            ),
            factor_def=fdef,
            data=data,
        )
        mean_fv = 0.0
        if len(fv) > 0 and "factor_value" in fv.columns:
            mean_fv = float(fv["factor_value"].drop_nulls().mean() or 0.0)
        return {
            "backtest_id": bt.id,
            "rows": len(fv),
            "mean_factor": mean_fv,
            "ic_mean": bt.ic_mean,
            "ic_ir": bt.ic_ir,
            "sharpe_ratio": bt.sharpe_ratio,
            "max_drawdown": bt.max_drawdown,
            "long_short_annual_return": bt.long_short_annual_return,
            "factor_values_path": str(bt.factor_values_path),
            "equity_curve_path": str(bt.equity_curve_path),
        }

    def _score_from_metrics(
        *,
        ic_mean: float,
        sharpe: float,
        dsr: float | None,
        pbo: float | None,
        max_drawdown: float,
    ) -> dict:
        """将核心指标映射到 0–100 分与 A/B/C/D 等级。"""
        score = 50.0
        # IC 贡献
        score += max(-20.0, min(20.0, ic_mean * 200.0))
        # Sharpe 贡献
        score += max(-15.0, min(20.0, sharpe * 10.0))
        # 回撤惩罚
        score -= max(0.0, min(15.0, abs(max_drawdown) * 30.0))
        if dsr is not None:
            score += max(-10.0, min(15.0, (dsr - 0.5) * 20.0))
        if pbo is not None:
            score -= max(0.0, min(20.0, pbo * 25.0))

        score = max(0.0, min(100.0, score))
        if score >= 80:
            grade = "A"
        elif score >= 65:
            grade = "B"
        elif score >= 50:
            grade = "C"
        else:
            grade = "D"
        return {"score": round(score, 1), "grade": grade}

    @mcp.tool()
    def score_factor(expression: str | None = None, backtest_id: str | None = None) -> dict:
        """多维度评分（0-100, A/B/C/D）。

        优先用 expression 现算；若仅提供 backtest_id，则尝试从 equity 曲线路径推断
        （当前实现：expression 路径为主）。
        """
        if not expression and not backtest_id:
            return {
                "score": 0,
                "grade": "D",
                "error": "Provide expression and/or backtest_id",
            }

        if expression:
            bt = run_backtest(expression)
            anti = run_anti_overfitting_from_equity(bt.get("equity_curve_path"))
            metrics = _score_from_metrics(
                ic_mean=float(bt.get("ic_mean") or 0.0),
                sharpe=float(bt.get("sharpe_ratio") or 0.0),
                dsr=anti.get("dsr"),
                pbo=anti.get("pbo"),
                max_drawdown=float(bt.get("max_drawdown") or 0.0),
            )
            return {
                **metrics,
                "backtest_id": bt.get("backtest_id"),
                "components": {
                    "ic_mean": bt.get("ic_mean"),
                    "sharpe_ratio": bt.get("sharpe_ratio"),
                    "max_drawdown": bt.get("max_drawdown"),
                    "dsr": anti.get("dsr"),
                    "pbo": anti.get("pbo"),
                },
            }

        return {
            "score": 0,
            "grade": "C",
            "note": "backtest_id-only lookup is limited; pass expression for full score",
            "backtest_id": backtest_id,
        }

    def run_anti_overfitting_from_equity(equity_path: str | None) -> dict:
        """从 equity 曲线 parquet 提取 long_short 收益并跑反过拟合。"""
        import numpy as np
        import polars as pl

        from reproagent.reproducer.anti_overfitting import (
            bootstrap_sharpe_ci,
            deflated_sharpe_ratio,
            min_backtest_length,
            placebo_test,
            prob_backtest_overfitting,
        )

        empty = {
            "dsr": None,
            "dsr_pvalue": None,
            "pbo": None,
            "min_btl": None,
            "sharpe_ci": None,
            "placebo_pvalue": None,
        }
        if not equity_path:
            return {**empty, "note": "No equity curve path"}

        from pathlib import Path

        path = Path(equity_path)
        if not path.exists():
            return {**empty, "note": f"Equity curve not found: {path}"}

        try:
            eq = pl.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            return {**empty, "note": f"Failed to read equity: {exc}"}

        # StrategyBacktester 写出 ls_return；兼容其他列名
        ret_col = None
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
                return {**empty, "note": "No return columns in equity curve"}
            ret_col = numeric[0]

        series = eq[ret_col].drop_nulls().to_numpy()
        if len(series) < 5:
            return {**empty, "note": f"Too few observations: {len(series)}"}

        rets = series.astype(float)

        rets = rets[np.isfinite(rets)]
        if len(rets) < 5:
            return {**empty, "note": "Insufficient finite returns"}

        sharpe = float(np.mean(rets) / (np.std(rets) + 1e-12) * np.sqrt(252))
        dsr = deflated_sharpe_ratio(sharpe, n_trials=10, n_obs=len(rets))
        pbo = prob_backtest_overfitting(rets, n_splits=min(5, max(2, len(rets) // 5)))
        min_btl = min_backtest_length(sharpe, variance=float(np.var(rets)))
        boot = bootstrap_sharpe_ci(rets, n_boot=200)

        # placebo 需要因子值面板；此处用收益随机置换近似
        placebo_p = None
        try:
            # 构造伪面板：date, asset, factor_value + forward return
            n = len(rets)
            fake_fv = pl.DataFrame(
                {
                    "date": list(range(n)),
                    "asset": ["A"] * n,
                    "factor_value": rets,
                }
            )
            fake_fwd = pl.DataFrame(
                {
                    "date": list(range(n)),
                    "asset": ["A"] * n,
                    "forward_return": np.roll(rets, -1),
                }
            )
            # placebo_test 签名可能不同，做兼容
            pr = placebo_test(fake_fv, fake_fwd, n_shuffles=50)
            placebo_p = getattr(pr, "pvalue", None) or (
                pr.get("pvalue") if isinstance(pr, dict) else None
            )
        except Exception:  # noqa: BLE001
            placebo_p = None

        return {
            "dsr": float(dsr.dsr),
            "dsr_pvalue": float(dsr.p_value),
            "pbo": float(pbo.pbo),
            "min_btl": int(min_btl.min_obs),
            "sharpe_ci": {
                "lower": float(boot.sharpe_ci_lower),
                "upper": float(boot.sharpe_ci_upper),
            },
            "placebo_pvalue": float(placebo_p) if placebo_p is not None else None,
            "n_obs": len(rets),
            "sharpe": sharpe,
        }

    @mcp.tool()
    def diagnose_factor(expression: str) -> dict:
        """失败模式诊断 + 改进建议。"""
        from reproagent.reproducer.lookahead_detector import detect_lookahead
        from reproagent.reproducer.polars_engine import validate_expression

        validation = validate_expression(expression)
        lookahead = detect_lookahead(expression)

        return {
            "expression": expression,
            "validation": validation,
            "lookahead": {
                "has_lookahead": lookahead.has_lookahead,
                "risk_level": lookahead.risk_level,
                "findings": [
                    {"rule": f.rule, "description": f.description, "severity": f.severity}
                    for f in lookahead.findings
                ],
            },
        }

    @mcp.tool()
    def run_anti_overfitting(backtest_id: str | None = None, expression: str | None = None) -> dict:
        """4+ 项反过拟合检验。

        推荐传 expression 现算；backtest_id  alone 时返回说明。
        """
        if expression:
            bt = run_backtest(expression)
            result = run_anti_overfitting_from_equity(bt.get("equity_curve_path"))
            result["backtest_id"] = bt.get("backtest_id")
            result["expression"] = expression
            return result

        if backtest_id:
            return {
                "dsr": None,
                "pbo": None,
                "min_btl": None,
                "placebo": None,
                "backtest_id": backtest_id,
                "note": "Pass expression=... to recompute anti-overfitting from a fresh backtest",
            }

        return {
            "dsr": None,
            "pbo": None,
            "min_btl": None,
            "placebo": None,
            "error": "Provide expression or backtest_id",
        }

    @mcp.tool()
    def list_universes() -> list[dict]:
        """列出可用股票池和基准。"""
        return [
            {"id": "csi300", "name": "沪深300", "benchmark": "000300.SH"},
            {"id": "csi500", "name": "中证500", "benchmark": "000905.SH"},
            {"id": "csi1000", "name": "中证1000", "benchmark": "000852.SH"},
            {"id": "all", "name": "全A股", "benchmark": "000300.SH"},
            {"id": "cb", "name": "全转债", "benchmark": "000832.SH"},
            {"id": "全转债", "name": "全转债", "benchmark": "000832.SH"},
        ]

    @mcp.tool()
    def search_factor_library(query: str = "", style: str | None = None) -> list[dict]:
        """搜索因子库。"""
        try:
            from reproagent.library.manager import FactorLibraryManager
            from reproagent.persistence.db import get_engine, init_db
            from reproagent.persistence.paths import AppPaths
            from reproagent.persistence.repository import Repository
            from reproagent.settings import get_settings

            settings = get_settings()
            engine = get_engine(settings.db_path)
            init_db(engine)
            repo = Repository(engine)
            paths = AppPaths.from_settings(settings)
            manager = FactorLibraryManager(repository=repo, paths=paths)
            entries = manager.list()
            results = []
            q = (query or "").lower()
            for e in entries:
                if style and e.factor.style != style:
                    continue
                name_l = e.factor.name.lower()
                cn_l = (e.factor.name_cn or "").lower()
                if q and q not in name_l and q not in cn_l:
                    continue
                results.append(
                    {
                        "id": e.id,
                        "name": e.factor.name,
                        "name_cn": e.factor.name_cn,
                        "style": e.factor.style,
                        "status": e.status,
                    }
                )
            return results
        except Exception:
            return []

    return mcp
