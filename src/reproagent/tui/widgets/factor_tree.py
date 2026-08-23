"""因子库树视图。"""

from __future__ import annotations

from textual.widgets import Tree


class FactorTree(Tree[str]):
    """按风格 / 标签组织的因子树。"""

    def __init__(self, label: str = "所有因子", **kwargs) -> None:  # noqa: ANN003
        super().__init__(label, **kwargs)
