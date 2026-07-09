"""领域模型序列化 / 校验冒烟测试。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from reproagent.cache.cache_key import compute_cache_key
from reproagent.library.versioning import bump, compute_dedup_hash
from reproagent.models import (
    BacktestParams,
    FactorDefinition,
    FactorInputField,
    ParsedFactorSpec,
    ReportedMetrics,
    ResearchReport,
    ToleranceConfig,
)
from reproagent.utils.hashing import content_hash


def test_research_report_roundtrip() -> None:
    report = ResearchReport(
        id="abc",
        file_path=Path("/tmp/x.pdf"),
        file_hash="deadbeef",
        page_count=10,
        ingested_at=datetime.now(UTC),
    )
    data = report.model_dump(mode="json")
    restored = ResearchReport.model_validate(data)
    assert restored.id == "abc"
    assert restored.page_count == 10
    assert restored.validation_status == "pending"


def test_parsed_factor_spec_with_metrics() -> None:
    spec = ParsedFactorSpec(
        id="f1",
        factor_name="momentum_20d",
        factor_name_cn="20日动量",
        description="近20日收益率",
        formula=r"r_{t-20,t}",
        input_fields=[
            FactorInputField(
                name="close",
                report_name="收盘价",
                data_type="price",
            )
        ],
        computation_steps=["pct_change(20)"],
        extraction_confidence=0.9,
        reported_metrics=ReportedMetrics(ic_mean=0.05, sharpe_ratio=1.2),
    )
    assert spec.reported_metrics is not None
    assert spec.reported_metrics.ic_mean == 0.05
    dumped = spec.model_dump()
    assert dumped["factor_name"] == "momentum_20d"


def test_tolerance_defaults() -> None:
    t = ToleranceConfig()
    assert t.ic_mean_abs == 0.03
    assert t.long_short_return_rel == 0.15


def test_backtest_params() -> None:
    p = BacktestParams(start_date=date(2020, 1, 1), end_date=date(2023, 12, 31))
    assert p.num_groups == 5
    assert p.benchmark == "000300.SH"


def test_compute_dedup_hash_stable() -> None:
    fd = FactorDefinition(
        id="1",
        spec_id="s1",
        name="m20",
        name_cn="动量",
        style="momentum",
        formula="close.pct_change(20)",
        input_fields=["volume", "close"],
        universe="全A股",
        rebalance_frequency="monthly",
    )
    h1 = compute_dedup_hash(fd)
    h2 = compute_dedup_hash(fd)
    assert h1 == h2
    assert len(h1) == 64


def test_semver_bump() -> None:
    assert bump("1.0.0", "patch") == "1.0.1"
    assert bump("1.0.0", "minor") == "1.1.0"
    assert bump("1.0.0", "major") == "2.0.0"


def test_cache_key_length() -> None:
    key = compute_cache_key("pdfhash", "1.0.0", "claude-sonnet-4-5")
    assert len(key) == 16


def test_content_hash() -> None:
    assert content_hash("hello") == content_hash(b"hello")
