"""因子衰减监控：周期性重新评估库内因子，检测 alpha 衰减。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal


@dataclass
class DecayStatus:
    """单因子衰减状态。"""

    factor_id: str
    original_ic: float  # 入库时的 IC
    current_ic: float  # 最近期的 IC
    ic_drop_ratio: float  # (original - current) / original (正数 = 衰减)
    evaluation_date: date
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
    """因子库衰减全景报告。"""

    total_checked: int
    stable: int
    decaying: int
    deprecated: int
    factors: list[DecayStatus] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DecayMonitor:
    """周期性重新评估库内因子，检测 alpha 衰减。

    使用场景：每周/每月运行一次，对所有 ready 状态的因子
    重新计算近期 IC，与入库时的 IC 对比。
    """

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
        """批量检查。

        Parameters
        ----------
        factors: {factor_id: (original_ic, current_ic)}
        """
        results = []
        for fid, (orig, curr) in factors.items():
            status = self.check_factor(fid, orig, curr)
            results.append(status)
        return results

    def generate_report(self) -> DecayReport:
        """生成衰减全景报告。"""
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
