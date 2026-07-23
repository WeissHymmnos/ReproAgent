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


# Function context
_CONTEXT: dict[str, Any] = {
    "pl": pl,
    "Rank": Rank,
    "CSRank": CSRank,
    "CSZScore": CSZScore,
    "Mean": Mean,
    "Std": Std,
    "Sum": Sum,
    "Ref": Ref,
    "Delta": Delta,
    "Abs": Abs,
    "Log": Log,
    "If": If,
    "Sign": Sign,
    "Sqrt": Sqrt,
    "Add": Add,
    "Sub": Sub,
    "Mul": Mul,
    "Div": Div,
    "Mult": Mult,
    "Divide": Divide,
    "Max": Max,
    "Min": Min,
    "Const": Const,
}

_CS_OPS = {"Rank", "CSRank", "CSZScore"}


class _ColFallback(dict):
    def __missing__(self, key: str) -> Any:
        return pl.col(key)


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
                return data.select(
                    ["date", "asset", pl.col("close").alias("factor_value")]
                )
            raise FormulaError(
                f"Unparseable factor formula {formula!r}: {e}"
            ) from e

        tmp_cols: list[str] = []
        df_container = [data]
        try:
            pl_expr = self._eval_ast_node(tree.body, df_container, tmp_cols)
            df = df_container[0]
            if isinstance(pl_expr, pl.Expr):
                df = df.with_columns(pl_expr.cast(pl.Float64).alias("factor_value"))
            else:
                df = df.with_columns(
                    pl.lit(pl_expr).cast(pl.Float64).alias("factor_value")
                )
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
                raise FormulaError(
                    f"Factor formula evaluation failed for {formula!r}: {e}"
                ) from e

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
                return left ** right
            raise ValueError(f"Unsupported binop: {type(node.op)}")

        if isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None
            func = _CONTEXT.get(func_name) if func_name else None
            if not func:
                raise ValueError(f"Unknown func {func_name}")

            is_cs = func_name in _CS_OPS
            args: list[Any] = []
            for arg_node in node.args:
                arg_val = self._eval_ast_node(arg_node, df_container, tmp_cols)
                if (
                    is_cs
                    and isinstance(arg_val, pl.Expr)
                    and not self._is_bare_col(arg_node)
                ):
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
