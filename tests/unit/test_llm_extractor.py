"""Unit tests for reproagent.parser.llm_extractor (mock fallback path)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from reproagent.models.report import ResearchReport
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.settings import Settings


def _settings_no_key() -> Settings:
    return Settings(_env_file=None, app_env="dev", allow_mock_llm=True, llm_api_key="")


def _report() -> ResearchReport:
    return ResearchReport(
        id="r-1",
        file_path=Path("/tmp/x.pdf"),
        file_hash="deadbeef",
        page_count=1,
        ingested_at=datetime.now(UTC),
    )


def test_extract_without_api_key_returns_mock_spec() -> None:
    ex = LLMExtractor(_settings_no_key())
    specs = ex.extract(_report(), "# mock markdown\n因子: 动量\n")
    assert isinstance(specs, list)
    assert len(specs) >= 1
    spec = specs[0]
    assert spec.factor_name
    assert spec.formula
    assert spec.extraction_confidence >= 0.0
    assert spec.input_fields


def test_extract_mock_spec_has_reported_metrics() -> None:
    ex = LLMExtractor(_settings_no_key())
    specs = ex.extract(_report(), "")
    assert specs[0].reported_metrics is not None
    assert specs[0].reported_metrics.ic_mean is not None


def test_revise_without_api_key_returns_modified_spec() -> None:
    from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec

    original = ParsedFactorSpec(
        id="f-1",
        factor_name="momentum_20d",
        factor_name_cn="动量",
        description="d",
        formula="close / Ref(close, 20) - 1",
        input_fields=[FactorInputField(name="close", report_name="收盘价", data_type="price")],
        computation_steps=["pct_change(20)"],
        extraction_confidence=0.9,
    )
    ex = LLMExtractor(_settings_no_key())
    revised = ex.revise("please fix the formula", original)
    assert revised.factor_name == original.factor_name
    assert revised.formula != original.formula
    assert "1.0" in revised.formula


def test_extract_does_not_call_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = LLMExtractor(_settings_no_key())

    def _fail_import(*args, **kwargs):
        raise AssertionError("real LLM client should not be imported without api key")

    monkeypatch.setattr("builtins.__import__", _fail_import)
    specs = ex.extract(_report(), "# md")
    assert len(specs) >= 1


def test_extract_mock_spec_id_stable() -> None:
    ex = LLMExtractor(_settings_no_key())
    specs_a = ex.extract(_report(), "")
    specs_b = ex.extract(_report(), "")
    assert specs_a[0].id == specs_b[0].id
