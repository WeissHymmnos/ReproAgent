"""分块提取与置信度门控单测。"""

from __future__ import annotations

from reproagent.models.factor_spec import DataDictMapping, FactorInputField, ParsedFactorSpec
from reproagent.parser.chunking import merge_factor_specs, needs_chunking, split_markdown_chunks
from reproagent.parser.confidence import evaluate_confidence
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.settings import Settings


def test_split_by_page_markers() -> None:
    md = "\n".join(
        [
            "<!-- page: 1 -->",
            "因子 A 说明 " * 50,
            "<!-- page: 2 -->",
            "因子 B 说明 " * 50,
            "<!-- page: 3 -->",
            "因子 C 说明 " * 50,
        ]
    )
    chunks = split_markdown_chunks(md, max_chars=200)
    assert len(chunks) >= 2
    assert any("page: 1" in c or "因子 A" in c for c in chunks)


def test_needs_chunking() -> None:
    assert not needs_chunking("short", threshold=100)
    assert needs_chunking("x" * 200, threshold=100)


def test_merge_factor_specs_prefers_higher_confidence() -> None:
    a = ParsedFactorSpec(
        id="1",
        factor_name="ytm",
        factor_name_cn="债性",
        description="",
        formula="ytm",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.4,
    )
    b = ParsedFactorSpec(
        id="2",
        factor_name="YTM",
        factor_name_cn="债性",
        description="",
        formula="ytm / Ref(ytm, 5)",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.9,
    )
    merged = merge_factor_specs([a, b])
    assert len(merged) == 1
    assert merged[0].extraction_confidence == 0.9
    assert "Ref" in merged[0].formula


def test_confidence_gate_low() -> None:
    spec = ParsedFactorSpec(
        id="x",
        factor_name="f",
        factor_name_cn="f",
        description="",
        formula="close",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.2,
    )
    gate = evaluate_confidence(spec)
    assert not gate.ok
    assert any("low_extraction_confidence" in r for r in gate.reasons)


def test_confidence_gate_warn_ratio() -> None:
    spec = ParsedFactorSpec(
        id="x",
        factor_name="f",
        factor_name_cn="f",
        description="",
        formula="close",
        input_fields=[
            FactorInputField(name="a", report_name="甲", data_type="price"),
            FactorInputField(name="b", report_name="乙", data_type="price"),
        ],
        computation_steps=[],
        extraction_confidence=0.9,
        data_dict_mappings=[
            DataDictMapping(
                report_term="甲", canonical_term="a", confidence=0.4, tag="WARN"
            ),
            DataDictMapping(
                report_term="乙", canonical_term="b", confidence=0.4, tag="WARN"
            ),
        ],
    )
    gate = evaluate_confidence(spec)
    assert not gate.ok
    assert any("warn_mapping" in r for r in gate.reasons)


def test_revise_by_root_cause_lookahead() -> None:
    settings = Settings(_env_file=None, app_env="dev", allow_mock_llm=True, llm_api_key="")
    ext = LLMExtractor(settings)
    spec = ParsedFactorSpec(
        id="1",
        factor_name="m",
        factor_name_cn="m",
        description="",
        formula="close / Ref(close, 5) - 1",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.9,
    )
    revised = ext.revise_by_root_cause(spec, "LOOKAHEAD_BIAS")
    assert "Ref(close, 1)" in revised.formula or revised.formula.startswith("Ref(")


def test_revise_by_root_cause_formula_error() -> None:
    settings = Settings(_env_file=None, app_env="dev", allow_mock_llm=True, llm_api_key="")
    ext = LLMExtractor(settings)
    spec = ParsedFactorSpec(
        id="1",
        factor_name="m",
        factor_name_cn="m",
        description="",
        formula="ytm",
        input_fields=[],
        computation_steps=[],
        extraction_confidence=0.9,
    )
    revised = ext.revise_by_root_cause(spec, "FORMULA_ERROR")
    assert revised.formula.startswith("CSZScore") or revised.formula.startswith("Rank")
