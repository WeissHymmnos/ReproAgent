"""因子库树视图。"""

from __future__ import annotations

from textual.widgets import Tree


class FactorTree(Tree[str]):
    """按风格 / 标签组织的因子树。"""

    def __init__(self) -> None:
        super().__init__("因子库")
