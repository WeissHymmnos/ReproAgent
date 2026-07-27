"""Unit tests for classify-first chart fusion (no model download)."""

from finreportparser.types import ChartType
from finreportparser.vlm.chart_classify import (
    fuse_classification,
    ocr_prior_from_texts,
    parse_vlm_label,
)


def test_parse_vlm_label_exact() -> None:
    t, c = parse_vlm_label("framework")
    assert t == ChartType.FRAMEWORK
    assert c >= 0.8


def test_parse_vlm_label_noisy() -> None:
    t, c = parse_vlm_label("The answer is: pie\n")
    assert t == ChartType.PIE


def test_ocr_prior_framework_stages() -> None:
    texts = [
        "图表1：因子研究方法演进图",
        "第一阶段：手动构建",
        "第二阶段：工程化构建",
        "第三阶段：大模型智能挖掘",
        "遗传规划（GP）",
        "深度学习（DL）",
        "强化学习（RL）",
        "综合来看",
        "方法论演进路径",
    ]
    t, conf, _ = ocr_prior_from_texts(texts)
    assert t == ChartType.FRAMEWORK
    assert conf >= 0.5


def test_fuse_overrides_pie_with_framework() -> None:
    cls = fuse_classification(
        vlm_type=ChartType.PIE,
        vlm_confidence=0.8,
        ocr_type=ChartType.FRAMEWORK,
        ocr_confidence=0.7,
    )
    assert cls.chart_type == ChartType.FRAMEWORK
    assert cls.source == "fusion"
    assert cls.rationale == "override_pie_with_ocr_structure"


def test_fuse_agreement() -> None:
    cls = fuse_classification(
        vlm_type=ChartType.LINE,
        vlm_confidence=0.7,
        ocr_type=ChartType.LINE,
        ocr_confidence=0.6,
    )
    assert cls.chart_type == ChartType.LINE
    assert cls.rationale == "agree"


def test_fuse_structure_pair_prefers_higher_conf() -> None:
    cls = fuse_classification(
        vlm_type=ChartType.FLOWCHART,
        vlm_confidence=0.85,
        ocr_type=ChartType.FRAMEWORK,
        ocr_confidence=0.95,
    )
    assert cls.chart_type == ChartType.FRAMEWORK
    assert cls.rationale == "structure_pair_ocr"
