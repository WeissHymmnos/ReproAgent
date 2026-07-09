"""Polars vs rqalpha 引擎一致性（待实现）。"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="引擎尚未实现")
@pytest.mark.parametrize("factor_name", ["momentum_20d", "roe_ttm", "turnover_20d"])
def test_engine_parity(factor_name: str) -> None:
    """验证 PolarsEngine 和 RiceQuantEval 对同一因子产出相同结果。"""
    raise NotImplementedError
