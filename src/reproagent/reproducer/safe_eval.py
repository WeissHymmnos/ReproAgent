"""受限求值器：安全地执行因子表达式。

从 aiminer/core/safe_eval.py 移植并适配 reproagent。
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

# 禁止在因子表达式中出现的名称
_FORBIDDEN_NAMES: set[str] = {
    "__import__",
    "__builtins__",
    "__loader__",
    "__spec__",
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "breakpoint",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "dir",
    "help",
    "exit",
    "quit",
    "type",
    "object",
    "super",
    "print",
}

_MAX_SOURCE_CHARS = 10_000
_MAX_AST_NODES = 1_000


class UnsafeExpressionError(ValueError):
    """表达式违反安全求值策略。"""


class _SecurityVisitor(ast.NodeVisitor):
    """拒绝不应出现在因子表达式中的构造。"""

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise UnsafeExpressionError(
                f"Access to private/dunder attribute '{node.attr}' is forbidden"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_NAMES or node.id.startswith("__"):
            raise UnsafeExpressionError(f"Use of name '{node.id}' is forbidden")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        raise UnsafeExpressionError("import statements are forbidden")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise UnsafeExpressionError("import statements are forbidden")

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAMES:
            raise UnsafeExpressionError(f"Call to '{node.func.id}' is forbidden")
        if isinstance(node.func, ast.Attribute) and node.func.attr in (
            "format",
            "format_map",
        ):
            # format 模板里的 {0.__class__} 属性遍历发生在运行时，AST 审计不可见
            raise UnsafeExpressionError(
                "str.format/format_map calls are forbidden "
                "(runtime attribute traversal bypasses AST audit)"
            )
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        raise UnsafeExpressionError("lambda expressions are forbidden")


def assert_safe_ast(tree: ast.AST) -> None:
    """若 AST 违反安全策略则抛出 UnsafeExpressionError。"""
    _SecurityVisitor().visit(tree)


def safe_compile(
    source: str | ast.AST,
    *,
    filename: str = "<factor>",
    mode: str = "eval",
) -> Any:
    """解析（如需要）、安全检查、编译表达式。"""
    if isinstance(source, str):
        if len(source) > _MAX_SOURCE_CHARS:
            raise UnsafeExpressionError(
                f"expression exceeds {_MAX_SOURCE_CHARS} characters"
            )
        tree = ast.parse(source, mode=mode)
    else:
        tree = source
    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > _MAX_AST_NODES:
        raise UnsafeExpressionError(
            f"expression exceeds {_MAX_AST_NODES} AST nodes ({node_count})"
        )
    assert_safe_ast(tree)
    ast.fix_missing_locations(tree)
    return compile(tree, filename=filename, mode=mode)


def safe_eval(
    source: str | ast.AST,
    context: Mapping[str, Any] | None = None,
    *,
    filename: str = "<factor>",
) -> Any:
    """在受限环境中求值表达式（空 builtins + 显式 operator context）。"""
    code = safe_compile(source, filename=filename, mode="eval")
    globals_dict: dict[str, Any] = {"__builtins__": {}}
    locals_mapping: Mapping[str, Any] = context if context is not None else {}
    return eval(code, globals_dict, locals_mapping)  # noqa: S307
