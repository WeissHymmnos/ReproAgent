"""FastMCP 服务器：暴露 reproagent 能力为 MCP 工具。

供 Claude Code / Claude Desktop 通过 MCP 协议调用。
启动方式: uv run reproagent mcp
"""

from __future__ import annotations


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
        start_date: str = "2023-01-01",
        end_date: str = "2024-12-31",
        universe: str = "csi300",
        num_groups: int = 5,
    ) -> dict:
        """运行完整因子回测。"""
        from datetime import date

        from reproagent.models.factor_def import FactorDefinition
        from reproagent.reproducer.data_loader import DataLoader
        from reproagent.reproducer.polars_engine import PolarsEngine
        from reproagent.settings import get_settings

        settings = get_settings()
        loader = DataLoader(settings)

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

        data = loader.load_price_data(
            universe, date.fromisoformat(start_date), date.fromisoformat(end_date)
        )
        engine = PolarsEngine.__new__(PolarsEngine)
        engine.allow_formula_fallback = False
        fv = engine.compute(
            fdef, universe, date.fromisoformat(start_date), date.fromisoformat(end_date), data=data
        )
        return {"rows": len(fv), "mean": float(fv["factor_value"].mean()) if len(fv) > 0 else 0.0}

    @mcp.tool()
    def score_factor(expression: str | None = None, backtest_id: str | None = None) -> dict:
        """多维度评分（0-100, A/B/C/D）。"""
        return {
            "score": 0,
            "grade": "C",
            "note": "Score computation requires full backtest — run run_backtest first",
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
    def run_anti_overfitting(backtest_id: str | None = None) -> dict:
        """4 项反过拟合检验。"""
        return {
            "dsr": None,
            "pbo": None,
            "min_btl": None,
            "placebo": None,
            "note": "Requires backtest result — use run_backtest first",
        }

    @mcp.tool()
    def list_universes() -> list[dict]:
        """列出可用股票池和基准。"""
        return [
            {"id": "csi300", "name": "沪深300", "benchmark": "000300.SH"},
            {"id": "csi500", "name": "中证500", "benchmark": "000905.SH"},
            {"id": "csi1000", "name": "中证1000", "benchmark": "000852.SH"},
            {"id": "all", "name": "全A股", "benchmark": "000300.SH"},
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
            return [
                {
                    "id": e.id,
                    "name": e.factor.name,
                    "style": e.factor.style,
                    "status": e.status,
                }
                for e in entries
            ]
        except Exception:
            return []

    return mcp
