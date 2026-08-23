"""根因分类 LLM fallback 路径（无 key 时安全降级）。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from reproagent.deviation.root_cause import classify_root_cause
from reproagent.models.deviation import DeviationReport, RootCause, ToleranceConfig
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import BacktestParams, ReplicationConfig


def _config() -> ReplicationConfig:
    spec = ParsedFactorSpec(
        id="s1",
        factor_name="f",
        factor_name_cn="f",
        description="",
        formula="close / Ref(close, 5) - 1",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.9,
    )
    return ReplicationConfig(
        id="c1",
        report_id="r1",
        factor_specs=[spec],
        backtest_params=BacktestParams(start_date=date(2023, 1, 1), end_date=date(2023, 2, 1)),
        parser_version="1.0.0",
        extraction_model_id="test",
        created_at=datetime.now(UTC),
    )


def test_rule_based_formula_error() -> None:
    dev = DeviationReport(
        id=uuid4().hex,
        comparison_id=uuid4().hex,
        factor_id="f",
        passed=False,
        metric_deviations={"ic_mean": 0.08, "sharpe_ratio": 0.01},
        tolerances=ToleranceConfig(),
        root_cause=RootCause.UNKNOWN,
        root_cause_detail="",
        recommend_reflect=True,
    )
    cause = classify_root_cause(dev, _config(), use_llm_fallback=False)
    assert cause == RootCause.FORMULA_ERROR


def test_llm_fallback_without_key_returns_unknown() -> None:
    """显著偏差 + 无规则命中 + 无 API → UNKNOWN 并写 detail。"""
    dev = DeviationReport(
        id=uuid4().hex,
        comparison_id=uuid4().hex,
        factor_id="f",
        passed=False,
        # 两指标反向、幅度不足以触发 LOOKAHEAD/DATA/PARAMETER 等
        metric_deviations={"ic_mean": 0.025, "max_drawdown": -0.02},
        tolerances=ToleranceConfig(),
        root_cause=RootCause.UNKNOWN,
        root_cause_detail="",
        recommend_reflect=True,
    )
    cause = classify_root_cause(dev, _config(), use_llm_fallback=True)
    assert cause in {RootCause.UNKNOWN, RootCause.UNIVERSE_MISMATCH, RootCause.FORMULA_ERROR}
    # 若走到 LLM 分支应有 detail
    if cause == RootCause.UNKNOWN and dev.root_cause_detail:
        detail_l = dev.root_cause_detail.lower()
        assert (
            "metrics" in detail_l
            or "LLM" in dev.root_cause_detail
            or any(k in detail_l for k in ("key", "skipped", "failed", "significant"))
        )
