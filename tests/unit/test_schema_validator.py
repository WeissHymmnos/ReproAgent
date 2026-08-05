"""Unit tests for reproagent.parser.schema_validator."""

from __future__ import annotations

import pytest

from reproagent.models.factor_spec import (
    DataDictMapping,
    FactorInputField,
    ParsedFactorSpec,
)
from reproagent.parser.schema_validator import SchemaValidator


def _make_spec(
    confidence: float = 0.9,
    mappings: list[DataDictMapping] | None = None,
    description: str = "A momentum factor.",
) -> ParsedFactorSpec:
    return ParsedFactorSpec(
        id="f1",
        factor_name="momentum_20d",
        factor_name_cn="20日动量",
        description=description,
        formula="close / Ref(close, 20) - 1",
        input_fields=[FactorInputField(name="close", report_name="收盘价", data_type="price")],
        computation_steps=["pct_change(20)"],
        extraction_confidence=confidence,
        data_dict_mappings=mappings or [],
    )


def test_validate_high_confidence_mapping_ok() -> None:
    mapping = DataDictMapping(
        report_term="收盘价",
        canonical_term="close",
        confidence=0.95,
        tag="OK",
    )
    spec = _make_spec(mappings=[mapping])
    out = SchemaValidator().validate(spec)
    assert out.data_dict_mappings[0].tag == "OK"


def test_validate_low_confidence_mapping_warn() -> None:
    mapping = DataDictMapping(
        report_term="换手率",
        canonical_term="turnover_rate",
        confidence=0.4,
        tag="OK",
    )
    spec = _make_spec(mappings=[mapping])
    out = SchemaValidator().validate(spec)
    assert out.data_dict_mappings[0].tag == "WARN"


def test_validate_low_extraction_confidence_adds_warn_note() -> None:
    spec = _make_spec(confidence=0.3, description="base desc")
    out = SchemaValidator().validate(spec)
    assert "[WARN]" in out.description
    assert "base desc" in out.description


def test_validate_high_extraction_confidence_no_note() -> None:
    spec = _make_spec(confidence=0.8, description="base desc")
    out = SchemaValidator().validate(spec)
    assert "[WARN]" not in out.description


def test_validate_empty_factor_name_raises() -> None:
    spec = _make_spec()
    spec = spec.model_copy(update={"factor_name": ""})
    with pytest.raises(ValueError):
        SchemaValidator().validate(spec)


def test_validate_empty_formula_raises() -> None:
    spec = _make_spec()
    spec = spec.model_copy(update={"formula": ""})
    with pytest.raises(ValueError):
        SchemaValidator().validate(spec)


def test_validate_all_batch() -> None:
    specs = [_make_spec(confidence=0.9), _make_spec(confidence=0.2)]
    out = SchemaValidator().validate_all(specs)
    assert len(out) == 2
    assert "[WARN]" not in out[0].description
    assert "[WARN]" in out[1].description


def test_validate_does_not_mutate_original() -> None:
    mapping = DataDictMapping(
        report_term="收盘价", canonical_term="close", confidence=0.4, tag="OK"
    )
    spec = _make_spec(mappings=[mapping])
    _ = SchemaValidator().validate(spec)
    assert spec.data_dict_mappings[0].tag == "OK"
