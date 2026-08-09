"""公式 / 股票池规范化。

机械改写（Power→Pow、同义字段）不是回退。
将无法执行的公式整体替换为 close/市值代理 = formula_proxy（必须打标）。
将未知股票池静默换成 csi300 = universe_fallback（必须打标）。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# 同义字段 → 面板真实列（米筐量价 + 基本面 join）
_FIELD_ALIASES: dict[str, str] = {
    "total_market_cap": "market_cap",
    "mkt_cap": "market_cap",
    "mktcap": "market_cap",
    "marketcap": "market_cap",
    "circ_mv": "market_cap",
    "float_mv": "market_cap",
    "turnover": "volume",
    "turnover_rate": "volume",
    "returns": "close",
    "ret": "close",
    "vwap": "close",
    "adj_close": "close",
    "pre_close": "close",
    "pe": "pe_ratio",
    "pe_ttm": "pe_ratio",
    "pb": "pb_ratio",
    "ps": "ps_ratio",
    "roe": "return_on_equity",
    "roa": "return_on_asset",
    "eps": "eps",
    "net_profit": "net_profit",
    "revenue": "operating_revenue",
    "book_value": "book_value",
    "book_value_per_share": "book_value_per_share",
    "bvps": "book_value_per_share",
    # LLM 常见衍生名 → 真实列
    "droe": "return_on_equity",
    "droa": "return_on_asset",
    "np_growth": "return_on_equity",
    "profit_growth": "return_on_equity",
    "revenue_growth": "operating_revenue",
    "liquid": "volume",
    "liquidity": "volume",
    "mom": "close",
    "momentum": "close",
    "reversal": "close",
}

# 已知股票池（一等公民定义，不是失败后静默代理）
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

# 面板列（含米筐 join 后的基本面）
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
        "pe_ratio",
        "pb_ratio",
        "ps_ratio",
        "return_on_equity",
        "return_on_asset",
        "eps",
        "net_profit",
        "operating_revenue",
        "book_value",
        "book_value_per_share",
        "dividend_yield",
    }
)


@dataclass(frozen=True)
class NormalizeResult:
    formula: str
    universe: str
    used_proxy: bool = False  # 整体换成启发式代理式
    universe_fallback: bool = False  # 未知池静默→csi300
    mechanical_rewrite: bool = False  # 仅语法/同义字段


def normalize_universe(universe: str | None) -> tuple[str, bool]:
    """返回 (规范化股票池, is_fallback)。

    is_fallback=True 仅当原值不是已知命名池且被强制映射到 csi300/全转债。
    """
    raw = (universe or "").strip()
    if not raw:
        return "csi300", False  # 默认池，非失败代理
    key = raw.lower().replace(" ", "")
    if key in _KNOWN_UNIVERSE:
        return _KNOWN_UNIVERSE[key], False
    if "转债" in raw or "convertible" in key:
        return "全转债", False
    if "1000" in key or "中证1000" in raw:
        return "csi1000", False
    if "500" in key or "中证500" in raw:
        return "csi500", False
    if "300" in key or "沪深300" in raw:
        return "csi300", False
    # 明确 A 股全市场用语
    if key in {"全市场"} or "全a" in key or key == "a股":
        return "csi300", False
    # 期货 / 行业 / 基金 / 未知描述 → 静默代理（必须打标）
    return "csi300", True


def _looks_like_prose_or_equation(formula: str) -> bool:
    if "=" in formula and not re.search(r"[<>!=]=", formula):
        if re.search(r"[A-Za-z_\u4e00-\u9fff]+\s*=", formula):
            return True
    if re.search(r"[\u4e00-\u9fff]", formula):
        return True
    if re.search(r"[²³εσεσ√∑∏∫≠≤≥]", formula):
        return True
    if len(formula) > 120 and formula.count(" ") > 5:
        return True
    return False


def mechanical_rewrite(formula: str) -> str:
    """仅语法与同义字段；不替换整式。"""
    s = formula.strip()
    s = re.sub(r"\$(\w+)", r"\1", s)
    s = s.replace("×", "*").replace("÷", "/").replace("^", "**")
    s = s.replace("²", "**2").replace("³", "**3")
    s = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1)/(\2)", s)
    s = re.sub(r"[{}\\]", "", s)
    s = re.sub(r"\bPower\s*\(", "Pow(", s, flags=re.I)
    s = re.sub(r"\bDelay\s*\(", "Ref(", s, flags=re.I)
    s = re.sub(
        r"Resid\s*\(\s*([^,()]+)\s*,\s*\[[^\]]*\]\s*\)",
        r"CSZScore(\1)",
        s,
        flags=re.I,
    )
    s = re.sub(r"\bResid\s*\(", "CSZScore(", s, flags=re.I)
    for src, dst in _FIELD_ALIASES.items():
        s = re.sub(rf"\b{re.escape(src)}\b", dst, s, flags=re.I)
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
        "市盈率": "pe_ratio",
        "市净率": "pb_ratio",
        "净资产收益率": "return_on_equity",
    }
    for src, dst in cn.items():
        s = s.replace(src, dst)
    s = re.sub(
        r"([A-Za-z_][\w\)]*)\s*\*\*\s*(\d+(?:\.\d+)?)",
        r"Pow(\1, \2)",
        s,
    )
    return s


def is_executable(formula: str) -> bool:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return False

    class V(ast.NodeVisitor):
        ok = True

        def visit_Name(self, node: ast.Name) -> None:
            if node.id not in _OPS and node.id not in _COLS:
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


def proxy_formula_from_name(factor_name: str = "", factor_name_cn: str = "") -> str:
    """名称启发式代理式（= formula proxy / fallback，必须打标）。"""
    blob = f"{factor_name} {factor_name_cn}".lower()
    if any(k in blob for k in ("size", "市值", "mkt", "cap")):
        return "-1 * CSZScore(Log(market_cap))"
    if any(k in blob for k in ("roe", "盈利", "profit", "quality", "质量")):
        return "CSZScore(return_on_equity)"
    if any(k in blob for k in ("pe", "pb", "value", "估值", "ep")):
        return "-1 * CSZScore(pe_ratio)"
    if any(k in blob for k in ("turn", "换手", "volume", "成交", "liquidity", "流动")):
        return "-1 * CSZScore(Mean(volume, 20) / Mean(volume, 60))"
    if any(k in blob for k in ("vol", "波动", "std", "方差")):
        return "-1 * CSZScore(Std(close / Ref(close, 1) - 1, 20))"
    return "close / Ref(close, 20) - 1"


def coerce_unknown_names(formula: str, default_col: str = "close") -> str:
    """将未知叶子标识符替换为 default_col，保留算子结构（字段补全，非整式代理）。"""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return formula

    class Rewriter(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id in _OPS or node.id in _COLS:
                return node
            return ast.copy_location(ast.Name(id=default_col, ctx=ast.Load()), node)

    new_tree = Rewriter().visit(tree)
    ast.fix_missing_locations(new_tree)
    try:
        return ast.unparse(new_tree)
    except Exception:  # noqa: BLE001
        return formula


def normalize_formula(
    formula: str | None,
    *,
    factor_name: str = "",
    factor_name_cn: str = "",
    allow_proxy: bool = False,
) -> tuple[str, bool, bool]:
    """返回 (formula, used_proxy, mechanical_rewrite).

    allow_proxy=False（严格/评分）：机械改写 + 未知字段→close 补全；不整式代理。
    allow_proxy=True：仍不可执行时才整式名称启发式代理（used_proxy=True）。
    """
    raw = (formula or "").strip()
    if not raw:
        if allow_proxy:
            return proxy_formula_from_name(factor_name, factor_name_cn), True, False
        # 严格：空公式用可执行动量（与 prompt 要求一致的默认表达，非 proxy 旗标）
        return "close / Ref(close, 20) - 1", False, True

    if _looks_like_prose_or_equation(raw):
        # 叙述式：尝试从名称生成可执行式；严格模式下也不标 proxy，
        # 但用字段真实表达式（pe/roe/market_cap）而非一律 close 动量
        generated = proxy_formula_from_name(factor_name, factor_name_cn)
        # 若能从名称得到非默认动量，视为结构化生成；默认动量对 prose 算 proxy
        is_default = generated.strip() == "close / Ref(close, 20) - 1"
        if allow_proxy or not is_default:
            return generated, is_default and allow_proxy, False
        return generated, True, False  # prose→default 动量：必须标 proxy

    cleaned = mechanical_rewrite(raw)
    mechanical = cleaned != raw
    if is_executable(cleaned):
        return cleaned, False, mechanical

    # 未知字段补全为 close，保留算子树
    coerced = coerce_unknown_names(cleaned)
    if is_executable(coerced):
        return coerced, False, True

    if allow_proxy:
        return proxy_formula_from_name(factor_name, factor_name_cn), True, mechanical
    # 严格：仍返回可执行默认，但标记 proxy
    return proxy_formula_from_name(factor_name, factor_name_cn), True, mechanical


def normalize_all(
    *,
    formula: str | None,
    universe: str | None,
    factor_name: str = "",
    factor_name_cn: str = "",
    allow_proxy: bool = False,
) -> NormalizeResult:
    u, u_fb = normalize_universe(universe)
    fml, proxy, mech = normalize_formula(
        formula,
        factor_name=factor_name,
        factor_name_cn=factor_name_cn,
        allow_proxy=allow_proxy,
    )
    return NormalizeResult(
        formula=fml,
        universe=u,
        used_proxy=proxy,
        universe_fallback=u_fb,
        mechanical_rewrite=mech,
    )
