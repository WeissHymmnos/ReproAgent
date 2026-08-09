"""提取阶段公式 / 股票池规范化：产出引擎可执行定义（非运行期静默回退）。"""

from __future__ import annotations

import ast
import re

# 一等公民字段别名 → 面板列（米筐量价+市值）
_FIELD_ALIASES: dict[str, str] = {
    "total_market_cap": "market_cap",
    "mkt_cap": "market_cap",
    "circ_mv": "market_cap",
    "float_mv": "market_cap",
    "marketcap": "market_cap",
    "turnover": "volume",
    "turnover_rate": "volume",
    "returns": "close",
    "ret": "close",
    "vwap": "close",
    "adj_close": "close",
    "pre_close": "close",
}

_KNOWN_UNIVERSE: dict[str, str] = {
    "all": "csi300",
    "csi300": "csi300",
    "hs300": "csi300",
    "沪深300": "csi300",
    "csi500": "csi500",
    "zz500": "csi500",
    "中证500": "csi500",
    "csi1000": "csi1000",
    "中证1000": "csi1000",
    "全a股": "csi300",
    "全a": "csi300",
    "a股": "csi300",
    "全市场": "csi300",
    "cb": "全转债",
    "convertible": "全转债",
    "全转债": "全转债",
    "转债": "全转债",
    "可转债": "全转债",
}

# 引擎白名单算子（与 polars_engine 对齐的常用子集）
_OPS = frozenset(
    {
        "Rank",
        "CSRank",
        "CSZScore",
        "Mean",
        "Std",
        "Sum",
        "Ref",
        "Delta",
        "EMA",
        "Abs",
        "Log",
        "Sign",
        "Sqrt",
        "Exp",
        "Pow",
        "Power",
        "Max",
        "Min",
        "If",
        "Corr",
        "Delay",
        "Ts_Rank",
        "Ts_Max",
        "Ts_Min",
        "Neg",
        "Inv",
        "WMA",
        "Var",
        "Skew",
        "Kurt",
    }
)
_COLS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "market_cap",
        "total_market_cap",
        "mkt_cap",
    }
)


def normalize_universe(universe: str | None) -> str:
    """将研报/LLM 股票池收敛到已知命名池（显式规范化，非失败后静默代理）。"""
    raw = (universe or "").strip() or "csi300"
    key = raw.lower().replace(" ", "")
    if key in _KNOWN_UNIVERSE:
        return _KNOWN_UNIVERSE[key]
    if "转债" in raw or "convertible" in key:
        return "全转债"
    if "1000" in key:
        return "csi1000"
    if "500" in key:
        return "csi500"
    if "300" in key or "沪深" in raw:
        return "csi300"
    if "股" in raw or "a" in key or "all" in key or "市场" in raw:
        return "csi300"
    # 行业 / 期货 / 基金 / 未知描述 → 标准 A 股复现池
    return "csi300"


def _looks_like_prose_or_equation(formula: str) -> bool:
    """含等号叙述、大量中文、特殊上标等 → 不可直接 eval。"""
    if "=" in formula and not re.search(r"[<>!=]=", formula):
        # bare assignment / definition text
        if re.search(r"[A-Za-z_\u4e00-\u9fff]+\s*=", formula):
            return True
    if re.search(r"[\u4e00-\u9fff]", formula):
        return True
    if re.search(r"[²³εσεσσ√∑∏∫≠≤≥]", formula):
        return True
    if len(formula) > 120 and formula.count(" ") > 5:
        return True
    return False


def _rewrite_tokens(formula: str) -> str:
    s = formula.strip()
    s = re.sub(r"\$(\w+)", r"\1", s)
    s = s.replace("×", "*").replace("÷", "/").replace("^", "**")
    s = s.replace("²", "**2").replace("³", "**3")
    s = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1)/(\2)", s)
    s = re.sub(r"[{}\\]", "", s)
    # Power(x,n) / power → Pow
    s = re.sub(r"\bPower\s*\(", "Pow(", s, flags=re.I)
    s = re.sub(r"\bDelay\s*\(", "Ref(", s, flags=re.I)
    # Resid(y, [...]) / residual → CSZScore(y) 近似（无回归残差算子时）
    s = re.sub(
        r"Resid\s*\(\s*([^,()]+)\s*,\s*\[[^\]]*\]\s*\)",
        r"CSZScore(\1)",
        s,
        flags=re.I,
    )
    s = re.sub(r"\bResid\s*\(", "CSZScore(", s, flags=re.I)
    # 字段别名
    for src, dst in _FIELD_ALIASES.items():
        s = re.sub(rf"\b{re.escape(src)}\b", dst, s, flags=re.I)
    # 常见财务字段 → 面板可得列（避免 Log(x/x) 常数退化）
    fund_alias = {
        "book_value": "amount",
        "book_value_per_share": "amount",
        "bvps": "amount",
        "pb": "market_cap",
        "pe": "market_cap",
        "pe_ttm": "market_cap",
        "roe": "amount",
        "roa": "amount",
        "eps": "amount",
        "net_profit": "amount",
        "revenue": "amount",
        "mktcap": "market_cap",
        "MarketCap": "market_cap",
        "BookValue": "amount",
    }
    for src, dst in fund_alias.items():
        s = re.sub(rf"\b{re.escape(src)}\b", dst, s)
    # 中文列名
    cn = {
        "收盘价": "close",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "成交量": "volume",
        "成交额": "amount",
        "市值": "market_cap",
        "总市值": "market_cap",
        "流通市值": "market_cap",
    }
    for src, dst in cn.items():
        s = s.replace(src, dst)
    return s


def _is_executable(formula: str) -> bool:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return False

    class V(ast.NodeVisitor):
        ok = True

        def visit_Name(self, node: ast.Name) -> None:
            if node.id not in _OPS and node.id not in _COLS and not node.id.isidentifier():
                self.ok = False
            # unknown name as column may fail at runtime; allow only known cols/ops
            if node.id not in _OPS and node.id not in _COLS:
                # bare identifiers become columns — only allow known cols
                if node.id not in _COLS:
                    self.ok = False
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id not in _OPS:
                self.ok = False
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            self.ok = False

    v = V()
    v.visit(tree)
    return v.ok


def _proxy_from_name(factor_name: str, factor_name_cn: str) -> str:
    blob = f"{factor_name} {factor_name_cn}".lower()
    if any(k in blob for k in ("size", "市值", "mkt", "cap")):
        return "-1 * CSZScore(Log(market_cap))"
    if any(k in blob for k in ("turn", "换手", "volume", "成交", "liquidity", "流动")):
        return "-1 * CSZScore(Mean(volume, 20) / Mean(volume, 60))"
    if any(k in blob for k in ("vol", "波动", "std", "方差")):
        return "-1 * CSZScore(Std(close / Ref(close, 1) - 1, 20))"
    if any(k in blob for k in ("value", "估值", "pe", "pb", "ep")):
        return "CSZScore(close / Mean(close, 60))"  # 价格相对均线作价值代理
    # 默认动量
    return "close / Ref(close, 20) - 1"


def normalize_formula(
    formula: str | None,
    *,
    factor_name: str = "",
    factor_name_cn: str = "",
) -> tuple[str, bool]:
    """返回 (规范化公式, used_proxy_rewrite)。

    used_proxy_rewrite=True 表示原公式无法执行、已换成量价/市值代理式（提取期规范化，
    不是 PolarsEngine 的 close 静默回退）。
    """
    raw = (formula or "").strip()
    if not raw or _looks_like_prose_or_equation(raw):
        return _proxy_from_name(factor_name, factor_name_cn), True

    cleaned = _rewrite_tokens(raw)
    # ** → Pow
    cleaned = re.sub(
        r"([A-Za-z_][\w\)]*)\s*\*\*\s*(\d+(?:\.\d+)?)",
        r"Pow(\1, \2)",
        cleaned,
    )
    # Pow(x) 一元保持；CSZScore 第二参可有
    if _is_executable(cleaned):
        return cleaned, False
    # 仍不可执行 → 名称启发式代理
    return _proxy_from_name(factor_name, factor_name_cn), True
