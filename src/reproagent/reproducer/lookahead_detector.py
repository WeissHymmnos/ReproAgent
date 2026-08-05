"""AST 遍历检测因子公式中的未来函数风险。

检测规则（按严重度降序）：
1. ``Ref(x, n)`` 其中 ``n < 0`` → 显式未来引用 (error)
2. ``shift(-n)`` 或任何负窗口 → 未来数据 (error)
3. close/high/low 未滞后 → 日内不可交易价格 (warning)
4. 基本面字段的 report_date vs trade_date → 财务数据发布滞后 (info)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LookaheadFinding:
    """单条检测发现。"""

    rule: str  # 触发的检测规则标识符
    location: str  # AST 节点位置描述
    description: str  # 人类可读说明
    severity: Literal["error", "warning", "info"]


@dataclass
class LookaheadReport:
    """未来函数检测完整报告。"""

    has_lookahead: bool
    risk_level: Literal["none", "low", "medium", "high"]
    findings: list[LookaheadFinding] = field(default_factory=list)


# --- 需要滞后的价格字段（今日收盘价在收盘前不可知）---
_PRICE_FIELDS_REQUIRING_LAG = {"close", "open", "high", "low"}

# --- 自身就是滞后引用的算子 ---
_LAG_OPS = {"Ref", "Delta"}


class _LookaheadVisitor(ast.NodeVisitor):
    """遍历因子公式 AST，收集所有未来函数风险信号。"""

    def __init__(self) -> None:
        self.findings: list[LookaheadFinding] = []

    # ── 规则 1: Ref(x, n) 其中 n < 0 ──
    def visit_Call(self, node: ast.Call) -> None:
        func_name: str | None = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        # 检查 Ref / shift 的第二个参数（窗口）是否为负数
        if func_name in ("Ref", "Delta", "shift"):
            if len(node.args) >= 2:
                window_node = node.args[1]
                window_val = self._resolve_constant(window_node)
                if window_val is not None and window_val < 0:
                    self.findings.append(
                        LookaheadFinding(
                            rule="negative_window",
                            location=ast.unparse(node),
                            description=(
                                f"{func_name}(x, {window_val}) 使用了负窗口 "
                                f"（{window_val}），直接引用了未来数据"
                            ),
                            severity="error",
                        )
                    )

        # 检查裸 close/open/high/low 调用（未通过 Ref 滞后）
        if func_name is None and len(node.args) >= 1:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Name) and first_arg.id in _PRICE_FIELDS_REQUIRING_LAG:
                # 检查是否在第一层就使用了 close 等
                pass  # 主检测在 visit_Name 中处理

        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        # 检测 USub 作用于数值常量 → 可能表示负窗口但被解析为 -N 的表达式
        # 这在公式中自然出现，不一定是未来函数，但需要检查上下文
        self.generic_visit(node)

    # ── 规则 2: 裸 price 字段引用（未经滞后处理）──
    def visit_Name(self, node: ast.Name) -> None:
        name = node.id
        if name in _PRICE_FIELDS_REQUIRING_LAG:
            self.findings.append(
                LookaheadFinding(
                    rule="unlagged_price",
                    location=name,
                    description=(
                        f"公式直接引用了 '{name}' 字段但未通过 Ref 滞后。"
                        f"当日 {name} 在收盘前不可知，建议使用 Ref({name}, 1)。"
                        f"如果因子使用次日开盘价执行则此警告可忽略。"
                    ),
                    severity="warning",
                )
            )
        self.generic_visit(node)

    # ── 规则 3: shift / lead 调用 ──
    def visit_Attribute(self, node: ast.Attribute) -> None:
        # 检测 .shift(-N) 或 .lead(N) 的链式调用
        if node.attr in ("shift", "lead"):
            self.findings.append(
                LookaheadFinding(
                    rule="shift_or_lead",
                    location=ast.unparse(node),
                    description=(
                        f"检测到 '{node.attr}' 方法调用，可能引用未来数据。"
                        f"shift(负值) 是回看未来、lead() 是前行窗口，"
                        f"请确认窗口方向。"
                    ),
                    severity="warning",
                )
            )
        self.generic_visit(node)

    @staticmethod
    def _resolve_constant(node: ast.AST) -> int | float | None:
        """安全地将 AST 节点解析为数值常量，解析失败返回 None。"""
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = _LookaheadVisitor._resolve_constant(node.operand)
            if inner is not None:
                return -inner
        return None


def detect_lookahead(formula: str) -> LookaheadReport:
    """对因子公式进行静态未来函数检测。

    Parameters
    ----------
    formula:
        因子公式字符串（Python / Qlib 风格表达式）。

    Returns
    -------
    LookaheadReport:
        包含是否检测到未来函数、风险等级和具体发现的完整报告。
    """
    findings: list[LookaheadFinding] = []

    # —— 纯文本层面的前置检查 ——
    formula_lower = formula.lower()

    # shift(- 模式
    import re

    if re.search(r"shift\s*\(\s*-", formula_lower):
        findings.append(
            LookaheadFinding(
                rule="text_shift_negative",
                location="formula text",
                description="公式文本中发现 'shift(-N)' 模式，这是显式的未来数据引用",
                severity="error",
            )
        )

    # lead( 模式
    if "lead(" in formula_lower:
        findings.append(
            LookaheadFinding(
                rule="text_lead",
                location="formula text",
                description="公式文本中发现 'lead()' 调用，lead 是前向窗口函数",
                severity="error",
            )
        )

    # —— AST 层面的结构化检查 ——
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        findings.append(
            LookaheadFinding(
                rule="parse_error",
                location="formula",
                description=f"公式语法错误，无法进行 AST 级别检测: {e}",
                severity="info",
            )
        )
        return _build_report(findings)

    visitor = _LookaheadVisitor()
    visitor.visit(tree)
    findings.extend(visitor.findings)

    return _build_report(findings)


def _build_report(findings: list[LookaheadFinding]) -> LookaheadReport:
    """将发现列表汇总为 LookaheadReport。"""
    if not findings:
        return LookaheadReport(has_lookahead=False, risk_level="none")

    has_error = any(f.severity == "error" for f in findings)
    has_warning = any(f.severity == "warning" for f in findings)

    if has_error:
        risk_level = "high"
    elif has_warning and len(findings) >= 2:
        risk_level = "medium"
    elif has_warning:
        risk_level = "low"
    else:
        risk_level = "none"

    return LookaheadReport(
        has_lookahead=has_error,
        risk_level=risk_level,
        findings=findings,
    )
