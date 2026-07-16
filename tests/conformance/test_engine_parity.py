"""Polars vs rqalpha 引擎一致性（待实现）。

引擎一致性校验需要 rqalpha 依赖（`pip install reproagent[rqalpha]`）以及
双引擎对同一因子定义产出可比结果的能力。当前 RiceQuantEval 仅为薄封装，
且 CI 环境不强制 rqdatac/rqalpha 凭证，故保持 skip。
待 Task 18 的 rqalpha 引擎完整实现并具备离线 fixture 后再启用。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason=(
        "rqalpha 引擎尚未完整实现（Task 18 薄封装阶段）；"
        "双引擎 parity 需要 rqalpha 依赖与离线 fixture，CI 不强制。"
    )
)
@pytest.mark.parametrize("factor_name", ["momentum_20d", "roe_ttm", "turnover_20d"])
def test_engine_parity(factor_name: str) -> None:
    """验证 PolarsEngine 和 RiceQuantEval 对同一因子产出相同结果。"""
    raise NotImplementedError