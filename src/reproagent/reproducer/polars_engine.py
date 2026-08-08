"""Polars 因子计算引擎。"""

from __future__ import annotations

import ast
import logging
import math
import re
from datetime import date
from typing import Any

import polars as pl

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import ReplicationConfig

# --- Operator Definitions (similar to aiminer) ---


def Rank(x: Any, n: Any = None) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.5)
    return x.rank(method="average").over("date") / x.count().over("date")


def CSRank(x: Any) -> Any:
    return Rank(x)


def CSZScore(x: Any, n: Any = None) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    mean = x.mean().over("date")
    std = x.std().over("date")
    std_safe = pl.when(std == 0).then(pl.lit(1.0)).otherwise(std)
    return (x - mean) / std_safe


def _get_int(n: Any, op_name: str = "Operator") -> int:
    try:
        if isinstance(n, pl.Expr):
            raise ValueError(f"{op_name} expects a constant integer.")
        return int(float(n))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid period value '{n}' for {op_name}.") from exc


def Mean(x: Any, n: Any = None) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    if n is None:
        return x.mean().over("date")
    return x.rolling_mean(window_size=_get_int(n, "Mean")).over("asset")


def Std(x: Any, n: Any = None) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    if n is None:
        return x.std().over("date")
    return x.rolling_std(window_size=_get_int(n, "Std")).over("asset")


def Sum(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x) * _get_int(n, "Sum"))
    return x.rolling_sum(window_size=_get_int(n, "Sum")).over("asset")


def Ref(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x.shift(_get_int(n, "Ref")).over("asset")


def Delta(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    return (x - x.shift(_get_int(n, "Delta"))).over("asset")


def _ensure_expr(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x


def Abs(x: Any) -> Any:
    return _ensure_expr(x).abs()


def Log(x: Any) -> Any:
    return _ensure_expr(x).log(base=math.e)


def Sign(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    return _ensure_expr(x).sign()


def Sqrt(x: Any) -> Any:
    return _ensure_expr(x).sqrt()


def If(cond: Any, a: Any, b: Any) -> Any:
    return pl.when(cond).then(a).otherwise(b)


def Add(a: Any, b: Any) -> Any:
    return a + b


def Sub(a: Any, b: Any) -> Any:
    return a - b


def Mul(a: Any, b: Any) -> Any:
    return a * b


def Div(a: Any, b: Any) -> Any:
    return a / b


def Mult(a: Any, b: Any) -> Any:
    return a * b


def Divide(a: Any, b: Any) -> Any:
    return a / b


def Max(a: Any, b: Any) -> Any:
    return pl.max_horizontal(a, b)


def Min(a: Any, b: Any) -> Any:
    return pl.min_horizontal(a, b)


def Const(x: Any) -> Any:
    return pl.lit(x)


# ── 新增算子 (Phase 4.1: 对齐 aiminer ~55+ 算子) ──


def Exp(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(math.exp(float(x)))
    return _ensure_expr(x).exp()


def Pow(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x) ** _get_int(n, "Pow"))
    return x.pow(_get_int(n, "Pow"))


def Neg(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(-float(x))
    return -x


def Inv(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(1.0 / float(x)) if float(x) != 0 else pl.lit(float("inf"))
    return 1.0 / x


def Ceil(x: Any) -> Any:
    return _ensure_expr(x).ceil()


def Floor(x: Any) -> Any:
    return _ensure_expr(x).floor()


# ── 时序滚动扩展 ──


def Median(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x.rolling_median(window_size=_get_int(n, "Median")).over("asset")


def EMA(x: Any, n: Any) -> Any:
    """指数移动平均 span=n"""
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x.ewm_mean(span=_get_int(n, "EMA")).over("asset")


def WMA(x: Any, n: Any) -> Any:
    """加权移动平均（线性衰减权重）"""
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    w = _get_int(n, "WMA")
    weights = pl.arange(1, w + 1, eager=True) / (w * (w + 1) / 2)
    return x.rolling_map(
        lambda s: (s * weights[-len(s) :]).sum() / weights[-len(s) :].sum(),
        window_size=w,
    ).over("asset")


def Var(x: Any, n: Any = None) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    if n is None:
        return x.var().over("date")
    return x.rolling_var(window_size=_get_int(n, "Var")).over("asset")


def Skew(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float("nan"))
    return x.rolling_skew(window_size=_get_int(n, "Skew")).over("asset")


def Kurt(x: Any, n: Any) -> Any:
    """滚动超额峰度。"""
    if isinstance(x, (int, float)):
        return pl.lit(float("nan"))
    return x.rolling_map(lambda s: s.kurtosis(), window_size=_get_int(n, "Kurt")).over("asset")


def Mad(x: Any, n: Any) -> Any:
    """滚动中位绝对偏差 MAD。"""
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    w = _get_int(n, "Mad")
    med = x.rolling_median(window_size=w).over("asset")
    return (x - med).abs().rolling_median(window_size=w).over("asset")


def Ts_Rank(x: Any, n: Any) -> Any:
    """时序排名：当前值在过去 n 天内的百分位"""
    if isinstance(x, (int, float)):
        return pl.lit(0.5)
    w = _get_int(n, "Ts_Rank")
    return x.rolling_map(
        lambda s: (s.arg_sort().arg_sort()[-1] + 1) / len(s) if len(s) > 0 else 0.5,
        window_size=w,
    ).over("asset")


def Ts_Max(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x.rolling_max(window_size=_get_int(n, "Ts_Max")).over("asset")


def Ts_Min(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    return x.rolling_min(window_size=_get_int(n, "Ts_Min")).over("asset")


def Ts_ArgMax(x: Any, n: Any) -> Any:
    """距离过去 n 天最大值的天数。"""
    if isinstance(x, (int, float)):
        return pl.lit(0)
    w = _get_int(n, "Ts_ArgMax")
    return (
        x.rolling_map(
            lambda s: len(s) - 1 - s.arg_max() if len(s) > 0 else 0,
            window_size=w,
        )
        .over("asset")
        .cast(pl.Float64)
    )


def Ts_ArgMin(x: Any, n: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0)
    w = _get_int(n, "Ts_ArgMin")
    return (
        x.rolling_map(
            lambda s: len(s) - 1 - s.arg_min() if len(s) > 0 else 0,
            window_size=w,
        )
        .over("asset")
        .cast(pl.Float64)
    )


def Ts_Percentile(x: Any, n: Any, p: Any = 50) -> Any:
    """滚动百分位数。"""
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    w = _get_int(n, "Ts_Percentile")
    import numpy as np

    return x.rolling_map(
        lambda s: np.percentile(s.to_numpy(), _get_int(p, "Ts_Percentile")),
        window_size=w,
    ).over("asset")


def Count(x: Any = None) -> Any:
    """非 nan 观测数。默认返回 1（每行一份观测）。"""
    if x is None:
        return pl.lit(1.0)
    return _ensure_expr(x).is_not_null().cast(pl.Float64)


# ── 关联 ──


def Corr(x: Any, y: Any, n: Any) -> Any:
    return pl.rolling_corr(x, y, window_size=_get_int(n, "Corr")).over("asset")


def Cov(x: Any, y: Any, n: Any) -> Any:
    return pl.rolling_cov(x, y, window_size=_get_int(n, "Cov")).over("asset")


# ── 截面扩展 ──


def GroupNeutral(x: Any) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(0.0)
    return x - x.mean().over("date")


def Winsorize(x: Any, pct: float = 0.05) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    lo = x.quantile(pct).over("date")
    hi = x.quantile(1.0 - pct).over("date")
    return pl.when(x < lo).then(lo).when(x > hi).then(hi).otherwise(x)


def Percentile(x: Any) -> Any:
    """截面百分位排名。"""
    if isinstance(x, (int, float)):
        return pl.lit(0.5)
    return Rank(x)


def Scale(x: Any, a: Any = 1.0) -> Any:
    if isinstance(x, (int, float)):
        return pl.lit(float(x))
    s = x.abs().sum().over("date")
    return x * _get_int(a, "Scale") / s


# ── 逻辑扩展 ──


def Greater(a: Any, b: Any) -> Any:
    return _ensure_expr(a) > _ensure_expr(b)


def Less(a: Any, b: Any) -> Any:
    return _ensure_expr(a) < _ensure_expr(b)


def GreaterEqual(a: Any, b: Any) -> Any:
    return _ensure_expr(a) >= _ensure_expr(b)


def LessEqual(a: Any, b: Any) -> Any:
    return _ensure_expr(a) <= _ensure_expr(b)


def Equal(a: Any, b: Any) -> Any:
    return _ensure_expr(a) == _ensure_expr(b)


def NotEqual(a: Any, b: Any) -> Any:
    return _ensure_expr(a) != _ensure_expr(b)


def And(*args: Any) -> Any:
    result = _ensure_expr(args[0])
    for a in args[1:]:
        result = result & _ensure_expr(a)
    return result


def Or(*args: Any) -> Any:
    result = _ensure_expr(args[0])
    for a in args[1:]:
        result = result | _ensure_expr(a)
    return result


def Not(a: Any) -> Any:
    return ~_ensure_expr(a)


def Clip(x: Any, lower: Any, upper: Any) -> Any:
    return _ensure_expr(x).clip(lower, upper)


# ── 别名 ──


def Plus(a: Any, b: Any) -> Any:
    return a + b


def Minus(a: Any, b: Any) -> Any:
    return a - b


def Multiply(a: Any, b: Any) -> Any:
    return a * b


def Subtract(a: Any, b: Any) -> Any:
    return a - b


def Negate(x: Any) -> Any:
    return Neg(x)


def Divi(a: Any, b: Any) -> Any:
    return a / b


def Correlation(x: Any, y: Any, n: Any) -> Any:
    return Corr(x, y, n)


# ── 算子注册表 ──

_CONTEXT: dict[str, Any] = {
    "pl": pl,
    # 截面
    "Rank": Rank,
    "CSRank": CSRank,
    "CSZScore": CSZScore,
    "GroupNeutral": GroupNeutral,
    "Winsorize": Winsorize,
    "Percentile": Percentile,
    "Scale": Scale,
    # 时序
    "Mean": Mean,
    "Std": Std,
    "Median": Median,
    "Sum": Sum,
    "Ref": Ref,
    "Delta": Delta,
    "EMA": EMA,
    "WMA": WMA,
    "Var": Var,
    "Skew": Skew,
    "Kurt": Kurt,
    "Mad": Mad,
    "Ts_Rank": Ts_Rank,
    "Ts_Max": Ts_Max,
    "Ts_Min": Ts_Min,
    "Ts_ArgMax": Ts_ArgMax,
    "Ts_ArgMin": Ts_ArgMin,
    "Ts_Percentile": Ts_Percentile,
    "Count": Count,
    # 关联
    "Corr": Corr,
    "Cov": Cov,
    "Correlation": Correlation,
    # 数学
    "Abs": Abs,
    "Log": Log,
    "Sign": Sign,
    "Sqrt": Sqrt,
    "Exp": Exp,
    "Pow": Pow,
    "Neg": Neg,
    "Inv": Inv,
    "Ceil": Ceil,
    "Floor": Floor,
    "Negate": Negate,
    # 逻辑
    "If": If,
    "Greater": Greater,
    "Less": Less,
    "GreaterEqual": GreaterEqual,
    "LessEqual": LessEqual,
    "Equal": Equal,
    "NotEqual": NotEqual,
    "And": And,
    "Or": Or,
    "Not": Not,
    "Clip": Clip,
    # 算术（含别名）
    "Add": Add,
    "Sub": Sub,
    "Mul": Mul,
    "Div": Div,
    "Mult": Mult,
    "Divide": Divide,
    "Multiply": Multiply,
    "Subtract": Subtract,
    "Divi": Divi,
    "Plus": Plus,
    "Minus": Minus,
    "Max": Max,
    "Min": Min,
    "Const": Const,
}

# 截面算子（参数需要预先物化）
_CS_OPS = {
    "Rank",
    "CSRank",
    "CSZScore",
    "GroupNeutral",
    "Winsorize",
    "Percentile",
    "Scale",
}

# 算子白名单（用于表达式校验）
_OPERATOR_WHITELIST: set[str] = set(_CONTEXT.keys()) - {"pl", "Const"}

# 字段白名单（Qlib 风格 $field 语法 + 裸字段 + 转债）
_FIELD_WHITELIST: set[str] = {
    "close",
    "open",
    "high",
    "low",
    "volume",
    "amount",
    "$close",
    "$open",
    "$high",
    "$low",
    "$volume",
    "$vwap",
    "trade_date",
    "date",
    "asset",
    "ts_code",
    # 转债 / 基本面扩展字段（与 DataLoader 规范化名对齐）
    "ytm",
    "premium_rate",
    "bond_value",
    "implied_vol",
    "option_value",
    "remaining_size",
    "conversion_price",
    "pe_ttm",
    "pb",
    "roe_ttm",
    "turnover_rate",
    "market_cap",
    "$ytm",
    "$premium_rate",
    "$bond_value",
    "$implied_vol",
    "$option_value",
    "$remaining_size",
}


class _ColFallback(dict):
    """eval() 命名空间：未知标识符 → pl.col(name)。同时处理 $field 语法。"""

    def __missing__(self, key: str) -> Any:
        # $field → strip $
        if key.startswith("$"):
            return pl.col(key[1:])
        return pl.col(key)


def validate_expression(expr: str) -> dict:
    """静态校验因子表达式的安全性和正确性。

    Returns
    -------
    dict with keys: valid (bool), errors (list[str]), warnings (list[str])
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not expr or not expr.strip():
        return {"valid": False, "errors": ["Expression is empty"], "warnings": []}

    # 1. 括号平衡
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            errors.append("Unbalanced parentheses: extra closing ')'")
            break
    if depth > 0:
        errors.append(f"Unbalanced parentheses: {depth} unclosed '('")

    # 2. AST 解析
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 3. 算子/字段白名单检查
    class _Validator(ast.NodeVisitor):
        def __init__(self) -> None:
            self.errors: list[str] = []
            self.warnings: list[str] = []

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name not in _OPERATOR_WHITELIST:
                    self.errors.append(f"Unknown operator: '{func_name}'")
                # Ref 负窗口检查
                if func_name in ("Ref", "Delta") and len(node.args) >= 2:
                    arg1 = node.args[1]
                    if isinstance(arg1, ast.Constant) and isinstance(arg1.value, (int, float)):
                        if arg1.value < 0:
                            self.errors.append(
                                f"{func_name} with negative window ({arg1.value}): "
                                f"this references future data"
                            )
                # Corr/Cov 自相关检查
                if func_name in ("Corr", "Cov", "Correlation") and len(node.args) >= 2:
                    a1 = ast.dump(node.args[0])
                    a2 = ast.dump(node.args[1])
                    if a1 == a2:
                        self.errors.append(f"{func_name}(a, a, n): self-correlation is a tautology")
                # Div tautology
                if func_name in ("Div", "Divi", "Divide") and len(node.args) >= 2:
                    a1 = ast.dump(node.args[0])
                    a2 = ast.dump(node.args[1])
                    if a1 == a2:
                        self.errors.append("Div(x, x): division by self is a tautology")
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            name = node.id
            # $ 前缀在 Python AST 中不会被解析为 Name（需要外部预处理）
            # 所以这里只检查裸字段名
            if name in ("close", "open", "high", "low"):
                self.warnings.append(
                    f"Bare price field '{name}' used without lag — "
                    f"intraday price not yet known at close. Consider Ref({name}, 1)."
                )
            self.generic_visit(node)

    validator = _Validator()
    validator.visit(tree)
    errors.extend(validator.errors)
    warnings.extend(validator.warnings)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


class PolarsEngine:
    """实现 FactorEngine Protocol。用 AST 解析并用 Polars 算子动态求值。"""

    def __init__(
        self,
        config: ReplicationConfig,
        *,
        allow_formula_fallback: bool = False,
    ) -> None:
        self.config = config
        self.allow_formula_fallback = allow_formula_fallback

    def compute(
        self,
        factor_def: FactorDefinition,
        universe: str,
        start: date,
        end: date,
        data: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """返回 [date, asset, factor_value]。"""
        from reproagent.exceptions import FormulaError

        if data is None:
            from reproagent.reproducer.data_loader import DataLoader
            from reproagent.settings import Settings

            loader = DataLoader(Settings())
            data = loader.load_price_data(universe, start, end)

        if "trade_date" in data.columns and "date" not in data.columns:
            data = data.rename({"trade_date": "date"})
        if "ts_code" in data.columns and "asset" not in data.columns:
            data = data.rename({"ts_code": "asset"})

        formula = factor_def.formula

        # 将公式里的一些奇怪符号去掉
        formula = re.sub(r"\$(\w+)", r"\1", formula)

        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError as e:
            if self.allow_formula_fallback:
                logging.getLogger(__name__).warning(
                    "Unparseable formula %r, falling back to close: %s", formula, e
                )
                return data.select(["date", "asset", pl.col("close").alias("factor_value")])
            raise FormulaError(f"Unparseable factor formula {formula!r}: {e}") from e

        tmp_cols: list[str] = []
        df_container = [data]
        try:
            pl_expr = self._eval_ast_node(tree.body, df_container, tmp_cols)
            df = df_container[0]
            if isinstance(pl_expr, pl.Expr):
                df = df.with_columns(pl_expr.cast(pl.Float64).alias("factor_value"))
            else:
                df = df.with_columns(pl.lit(pl_expr).cast(pl.Float64).alias("factor_value"))
        except FormulaError:
            raise
        except Exception as e:
            if self.allow_formula_fallback:
                logging.getLogger(__name__).warning(
                    "AST evaluation failed for %s: %s (null factor values)",
                    formula,
                    e,
                )
                df = df_container[0].with_columns(
                    pl.lit(None).cast(pl.Float64).alias("factor_value")
                )
            else:
                raise FormulaError(f"Factor formula evaluation failed for {formula!r}: {e}") from e

        cols_to_drop = [c for c in tmp_cols if c in df.columns]
        if cols_to_drop:
            df = df.drop(cols_to_drop)

        return df.select(["date", "asset", "factor_value"]).drop_nulls()

    def _eval_ast_node(
        self,
        node: ast.AST,
        df_container: list[pl.DataFrame],
        tmp_cols: list[str],
    ) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            return _CONTEXT.get(node.id, pl.col(node.id))

        if isinstance(node, ast.BinOp):
            left = self._eval_ast_node(node.left, df_container, tmp_cols)
            right = self._eval_ast_node(node.right, df_container, tmp_cols)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError(f"Unsupported binop: {type(node.op)}")

        if isinstance(node, ast.UnaryOp):
            operand = self._eval_ast_node(node.operand, df_container, tmp_cols)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.Not):
                return ~operand if isinstance(operand, pl.Expr) else (not operand)
            raise ValueError(f"Unsupported unaryop: {type(node.op)}")

        if isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None
            func = _CONTEXT.get(func_name) if func_name else None
            if not func:
                raise ValueError(f"Unknown func {func_name}")

            is_cs = func_name in _CS_OPS
            args: list[Any] = []
            for arg_node in node.args:
                arg_val = self._eval_ast_node(arg_node, df_container, tmp_cols)
                if is_cs and isinstance(arg_val, pl.Expr) and not self._is_bare_col(arg_node):
                    tmp = f"__cs_arg_{len(tmp_cols)}__"
                    df_container[0] = df_container[0].with_columns(arg_val.alias(tmp))
                    tmp_cols.append(tmp)
                    arg_val = pl.col(tmp)
                args.append(arg_val)
            return func(*args)

        raise ValueError(f"Unsupported node {type(node)}")

    @staticmethod
    def _is_bare_col(node: ast.AST) -> bool:
        return isinstance(node, ast.Name)
