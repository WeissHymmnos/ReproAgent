"""偏差可视化仪表。"""

from __future__ import annotations

from textual.widgets import Static


class DeviationGauge(Static):
    """展示各指标相对容忍区间的偏差。"""

    def set_deviations(self, deviations: dict[str, float]) -> None:
        """更新显示数据。"""
        lines = [f"{k}: {v:.4f}" for k, v in deviations.items()] or ["无偏差数据"]
        self.update("\n".join(lines))
