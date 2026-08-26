"""MCP 服务：把复现引擎暴露给支持 MCP 的客户端。启动：uv run reproagent mcp"""

from __future__ import annotations

import logging
from typing import Any


def _score_from_metrics(
    *,
    ic_mean: float,
    sharpe: float,
    dsr: float | None,
    pbo: float | None,
    max_drawdown: float,
) -> dict:
    """Map core metrics to a 0–100 score and A/B/C/D grade."""
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


def placebo_pvalue_from_result(result: Any) -> float | None:
    from reproagent.reproducer.overfit_eval import placebo_pvalue_from_result as _impl

    return _impl(result)


def run_anti_overfitting_from_equity(equity_path: str | None) -> dict:
    from reproagent.reproducer.overfit_eval import evaluate_from_equity

    return evaluate_from_equity(equity_path)


def _library_entry_for_grade(backtest_id: str) -> Any:
    """Resolve a library row by entry id or backtest_result_id."""
    from sqlmodel import Session, select

    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.repository import Repository
    from reproagent.persistence.tables import FactorLibraryTable
    from reproagent.settings import get_settings

    token = (backtest_id or "").strip()
    if not token:
        return None
    settings = get_settings()
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    entry = repo.get_library_entry(token)
    if entry is not None:
        return entry
    with Session(engine) as session:
        row = session.exec(
            select(FactorLibraryTable)
            .where(FactorLibraryTable.backtest_result_id == token)
            .limit(1)
        ).first()
    if row is None:
        return None
    return repo.get_library_entry(row.id)


def library_grade(expression: str | None, backtest_id: str | None = None) -> dict[str, Any]:
    """0-100 grade from an expression (and optional backtest_id). Does not import FastMCP."""
    if not expression and not backtest_id:
        return {
            "score": 0,
            "grade": "D",
            "error": "Provide expression and/or backtest_id",
            "scorer": "library_grade",
        }
    if expression:
        from reproagent.reproducer.backtest_bundle import build_backtest_bundle

        bt = build_backtest_bundle(expression)
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
            "scorer": "library_grade",
        }
    entry = _library_entry_for_grade(str(backtest_id))
    if entry is not None:
        stored = dict(getattr(entry, "metrics", None) or {})
        folder = None
        try:
            from reproagent.reproducer.metrics import find_backtest_artifact_dir
            from reproagent.settings import get_settings

            folder = find_backtest_artifact_dir(get_settings().data_dir, entry)
        except Exception:  # noqa: BLE001
            folder = None
        equity = str(folder / "equity_curve.parquet") if folder is not None else None
        anti = run_anti_overfitting_from_equity(equity)
        scored = _score_from_metrics(
            ic_mean=float(stored.get("ic") or 0.0),
            sharpe=float(stored.get("sharpe") or 0.0),
            dsr=anti.get("dsr"),
            pbo=anti.get("pbo"),
            max_drawdown=float(stored.get("max_drawdown") or 0.0),
        )
        return {
            **scored,
            "backtest_id": backtest_id,
            "library_id": getattr(entry, "id", None),
            "components": {
                "ic_mean": stored.get("ic"),
                "sharpe_ratio": stored.get("sharpe"),
                "max_drawdown": stored.get("max_drawdown"),
                "dsr": anti.get("dsr"),
                "pbo": anti.get("pbo"),
            },
            "scorer": "library_grade",
        }
    return {
        "score": 0,
        "grade": "D",
        "error": (
            f"library entry not found: {backtest_id}. Score by backtest_id "
            "requires the factor to be registered in the library; to score a "
            "fresh backtest pass expression= instead (or read score from "
            "run_backtest output)."
        ),
        "backtest_id": backtest_id,
        "scorer": "library_grade",
    }


def library_grade_impl(expression: str | None, backtest_id: str | None = None) -> dict:
    """Module-level 0-100 grade used by FastMCP and finaince.tools."""
    return library_grade(expression, backtest_id)


def search_factor_library_impl(
    query: str = "",
    style: str | None = None,
    *,
    limit: int = 50,
) -> list[dict]:
    """Search the factor library without constructing FastMCP."""
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.models.library import LibraryFilter
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
    filter_ = LibraryFilter(style=style) if style else None
    cap = None if int(limit) <= 0 else max(1, int(limit))
    entries = manager.list(filter_, query=query, limit=cap)
    return [
        {
            "id": entry.id,
            "name": entry.factor.name,
            "name_cn": entry.factor.name_cn,
            "style": entry.factor.style,
            "status": entry.status,
        }
        for entry in entries
    ]


def build_mcp_server() -> object:
    """构建 FastMCP 服务。"""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires the official MCP SDK. Install with: uv sync --extra mcp"
        )

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
        """计算因子值并回测，附带 0-100 评分。"""
        from reproagent.reproducer.backtest_bundle import build_backtest_bundle

        out = build_backtest_bundle(
            expression,
            start_date=start_date,
            end_date=end_date,
            universe=universe,
            num_groups=num_groups,
        )
        grade = library_grade(expression)
        return {
            "backtest_id": out.get("backtest_id"),
            "rows": out.get("rows"),
            "mean_factor": out.get("mean_factor", 0.0),
            "ic_mean": out.get("ic_mean"),
            "ic_ir": out.get("ic_ir"),
            "sharpe_ratio": out.get("sharpe_ratio"),
            "max_drawdown": out.get("max_drawdown"),
            "long_short_annual_return": out.get("long_short_annual_return"),
            "factor_values_path": out.get("factor_values_path"),
            "equity_curve_path": out.get("equity_curve_path"),
            "score": {
                k: grade[k] for k in ("score", "grade") if k in grade
            },
        }

    @mcp.tool()
    def score_factor(expression: str | None = None, backtest_id: str | None = None) -> dict:
        """0-100 评分（A/B/C/D）。有 expression 就现算；否则按 backtest_id 查库。"""
        try:
            from finaince.tools import handle_score_factor

            return handle_score_factor(expression=expression, backtest_id=backtest_id)
        except ImportError:
            pass
        return library_grade(expression, backtest_id)

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
        """DSR / PBO 等反过拟合检验。需要 expression 才能现算。"""
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
    def list_feeds() -> dict:
        """列出 ReproAgent 数据源及其配置健康状态。"""
        from reproagent.market.catalog import probe_feeds
        from reproagent.settings import get_settings

        return probe_feeds(get_settings())

    @mcp.tool()
    def market_quotes(universe: str = "all", limit: int = 40) -> dict:
        """当前数据源最近交易日报价，按涨跌幅排序。"""
        from reproagent.market.tape import build_market_snapshot
        from reproagent.settings import get_settings

        return build_market_snapshot(get_settings(), universe=universe, limit=limit)

    @mcp.tool()
    def search_factor_library(query: str = "", style: str | None = None) -> list[dict]:
        """搜索因子库。"""
        try:
            from finaince.tools import handle_search_library

            payload = handle_search_library(query=query, style=style)
            return list(payload.get("items") or [])
        except ImportError:
            pass
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "finaince search library failed, falling back: %s", exc
            )
        try:
            return search_factor_library_impl(query, style, limit=50)
        except Exception as exc:
            logging.getLogger(__name__).warning("library search failed: %s", exc)
            return []

    return mcp
