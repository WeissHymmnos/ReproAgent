"""业界标准默认容忍区间。

IC (absolute):
  < 0.01 弱 | 0.01-0.03 可接受 | 0.03-0.05 强 | > 0.05 极强
  容忍: |ΔIC| ≤ 0.03

ICIR:
  < 0.2 弱 | 0.2-0.5 可接受 | 0.5-1.0 强 | > 1.0 极强
  容忍: |ΔICIR| ≤ 0.2

Sharpe: 相对偏差 15-20%（模型用绝对 0.3 作为简化默认）
Max Drawdown: 绝对 ±5%
年化收益: 相对 10-15%
"""

from __future__ import annotations

from reproagent.models.deviation import ToleranceConfig

DEFAULT_TOLERANCES = ToleranceConfig(
    ic_mean_abs=0.03,
    ic_ir_abs=0.2,
    long_short_return_rel=0.15,
    sharpe_abs=0.3,
    max_drawdown_abs=0.05,
)
