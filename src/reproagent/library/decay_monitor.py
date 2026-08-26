"""因子衰减监控：周期性重新评估库内因子，检测 alpha 衰减。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal


@dataclass
class DecayStatus:
    """单因子衰减状态。"""

    factor_id: str
    original_ic: float  # 入库时的 IC
    current_ic: float  # 最近期的 IC
    evaluation_date: date
    ic_drop_ratio: float = 0.0  # (original - current) / original（正数 = 衰减；__post_init__ 重算）
    status: Literal["stable", "decaying", "deprecated"] = "stable"

    def __post_init__(self) -> None:
        if self.original_ic > 0:
            drop = (self.original_ic - self.current_ic) / self.original_ic
            self.ic_drop_ratio = max(drop, -1.0)
        elif self.current_ic > 0:
            self.ic_drop_ratio = -1.0  # 改善
        else:
            self.ic_drop_ratio = 0.0

        if self.ic_drop_ratio > 0.5:
            self.status = "deprecated"
        elif self.ic_drop_ratio > 0.3:
            self.status = "decaying"


@dataclass
class DecayReport:
    """因子库衰减报告。"""

    total_checked: int
    stable: int
    decaying: int
    deprecated: int
    factors: list[DecayStatus] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DecayMonitor:
    """把入库 IC 和近期 IC 对比，标 stable / decaying / deprecated。"""

    def __init__(self, ic_drop_threshold: float = 0.5) -> None:
        self.ic_drop_threshold = ic_drop_threshold
        self._statuses: dict[str, DecayStatus] = {}

    def check_factor(
        self,
        factor_id: str,
        original_ic: float,
        current_ic: float,
        eval_date: date | None = None,
    ) -> DecayStatus:
        """检查单个因子的衰减状态。"""
        status = DecayStatus(
            factor_id=factor_id,
            original_ic=original_ic,
            current_ic=current_ic,
            evaluation_date=eval_date or date.today(),
        )
        self._statuses[factor_id] = status
        return status

    def check_all(self, factors: dict[str, tuple[float, float]]) -> list[DecayStatus]:
        """{factor_id: (original_ic, current_ic)}。"""
        results = []
        for fid, (orig, curr) in factors.items():
            status = self.check_factor(fid, orig, curr)
            results.append(status)
        return results

    def generate_report(self) -> DecayReport:
        """汇总当前已检查因子。"""
        statuses = list(self._statuses.values())
        return DecayReport(
            total_checked=len(statuses),
            stable=sum(1 for s in statuses if s.status == "stable"),
            decaying=sum(1 for s in statuses if s.status == "decaying"),
            deprecated=sum(1 for s in statuses if s.status == "deprecated"),
            factors=statuses,
        )

    def get_deprecated(self) -> list[str]:
        """返回所有已弃用的因子 ID。"""
        return [s.factor_id for s in self._statuses.values() if s.status == "deprecated"]

    def mark_deprecated_if_decayed(
        self,
        factor_id: str,
        original_ic: float,
        current_ic: float,
    ) -> bool:
        """检查并自动标记：IC 下降超过阈值返回 True。"""
        status = self.check_factor(factor_id, original_ic, current_ic)
        if status.ic_drop_ratio >= self.ic_drop_threshold:
            status.status = "deprecated"
            return True
        return False


def run_library_decay_check(
    pairs: dict[str, tuple[float, float]],
    *,
    eval_date: date | None = None,
) -> DecayReport:
    """{factor_id: (original_ic, current_ic)} → DecayReport。"""
    monitor = DecayMonitor()
    for fid, (orig, curr) in pairs.items():
        monitor.check_factor(fid, orig, curr, eval_date=eval_date)
    return monitor.generate_report()


def _finite_or_none(value: Any) -> float | None:
    """0.0 is a real IC; only None / NaN / non-numeric are missing."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def original_ic_from_metrics(metrics: dict[str, Any]) -> float | None:
    for key in ("ic", "ic_mean"):
        parsed = _finite_or_none(metrics.get(key))
        if parsed is not None:
            return parsed
    return None


def current_ic_from_artifacts(
    data_dir: Any,
    entry: Any,
    *,
    tail: int = 20,
) -> float | None:
    """Mean of the last ``tail`` rows in ``ic.parquet`` (0.0 is valid)."""
    if data_dir is None:
        return None
    from pathlib import Path

    import polars as pl

    from reproagent.reproducer.metrics import find_backtest_artifact_dir

    folder = find_backtest_artifact_dir(Path(data_dir), entry)
    if folder is None:
        return None
    icp = folder / "ic.parquet"
    if not icp.is_file():
        return None
    try:
        df = pl.read_parquet(icp)
    except Exception:  # noqa: BLE001
        return None
    if "ic" not in df.columns:
        return None
    series = df["ic"].drop_nulls()
    if series.len() == 0:
        return None
    n = max(1, min(int(tail), series.len()))
    mean = series.tail(n).mean()
    return _finite_or_none(mean)


def pairs_from_library_entries(
    entries: list[Any],
    data_dir: Any | None = None,
    *,
    tail: int = 20,
) -> dict[str, tuple[float, float]]:
    """original_ic from stored metrics; current_ic from ic.parquet tail.

    Never substitutes original when current is missing or 0.0.
    """
    pairs: dict[str, tuple[float, float]] = {}
    for entry in entries:
        metrics = dict(getattr(entry, "metrics", None) or {})
        orig = original_ic_from_metrics(metrics)
        if orig is None:
            continue
        current = current_ic_from_artifacts(data_dir, entry, tail=tail)
        if current is None:
            current = _finite_or_none(metrics.get("ic_recent"))
        if current is None:
            current = _finite_or_none(metrics.get("current_ic"))
        if current is None:
            continue
        fid = str(getattr(entry, "id", "") or "")
        if fid:
            pairs[fid] = (orig, current)
    return pairs
