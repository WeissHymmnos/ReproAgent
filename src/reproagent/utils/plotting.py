"""图表生成工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # isort: skip


def save_equity_curve_chart(
    equity_data: Any,
    output_path: Path,
    title: str = "Equity Curve",
) -> Path:
    """将净值曲线保存为 PNG/HTML。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        if isinstance(equity_data, dict):
            x = list(equity_data.keys())
            y = list(equity_data.values())
            ax.plot(x, y)
        elif hasattr(equity_data, "index") and hasattr(equity_data, "values"):
            ax.plot(equity_data.index, equity_data.values)
        else:
            ax.plot(equity_data)

        ax.set_title(title)
        ax.set_xlabel("Time")
        ax.set_ylabel("Equity")
        ax.grid(True)
        fig.savefig(output_path, bbox_inches="tight")
    finally:
        plt.close(fig)

    return output_path


def save_group_returns_chart(
    group_returns: dict[int, float],
    output_path: Path,
    title: str = "Group Returns",
) -> Path:
    """分组年化收益柱状图。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        groups = sorted(group_returns.keys())
        returns = [group_returns[g] for g in groups]

        bars = ax.bar([str(g) for g in groups], returns)

        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{height:.4f}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )

        ax.set_title(title)
        ax.set_xlabel("Group")
        ax.set_ylabel("Return")
        ax.grid(True, axis="y")
        fig.savefig(output_path, bbox_inches="tight")
    finally:
        plt.close(fig)

    return output_path


def save_ic_timeseries_chart(
    ic_series: Any,
    output_path: Path,
    title: str = "IC Time Series",
) -> Path:
    """IC 时序图。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        if isinstance(ic_series, dict):
            x = list(ic_series.keys())
            y = list(ic_series.values())
            ax.plot(x, y, label="IC")
        elif hasattr(ic_series, "index") and hasattr(ic_series, "values"):
            ax.plot(ic_series.index, ic_series.values, label="IC")
        else:
            ax.plot(ic_series, label="IC")

        ax.axhline(0, color="red", linestyle="--", alpha=0.5)
        ax.set_title(title)
        ax.set_xlabel("Time")
        ax.set_ylabel("IC")
        ax.grid(True)
        ax.legend()
        fig.savefig(output_path, bbox_inches="tight")
    finally:
        plt.close(fig)

    return output_path
