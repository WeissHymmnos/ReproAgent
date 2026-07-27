"""Chart classification: edge VLM + OCR signal fusion.

Pipeline contract (classify-first):
  1. OCR prior — layout/text cues from PaddleOCR (cheap, offline)
  2. Edge VLM prior — small vision-language model (SmolVLM-256M etc.)
  3. Fusion — reconcile disagreements (e.g. framework vs pie false positive)

Classification is independent of description so routing can pick type-specific
templates (axis charts vs framework cards vs tables).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from finreportparser.types import ChartClassification, ChartType

logger = logging.getLogger(__name__)

# Canonical labels the edge VLM is asked to pick from.
CHART_TYPE_LABELS: tuple[ChartType, ...] = (
    ChartType.BAR,
    ChartType.LINE,
    ChartType.PIE,
    ChartType.SCATTER,
    ChartType.HEATMAP,
    ChartType.FRAMEWORK,
    ChartType.FLOWCHART,
    ChartType.TABLE,
    ChartType.OTHER,
)

CHART_TYPE_ZH: dict[ChartType, str] = {
    ChartType.BAR: "柱状图",
    ChartType.LINE: "折线图",
    ChartType.PIE: "饼图",
    ChartType.SCATTER: "散点图",
    ChartType.HEATMAP: "热力图",
    ChartType.FRAMEWORK: "框架/方法论图",
    ChartType.FLOWCHART: "流程图",
    ChartType.TABLE: "表格图",
    ChartType.OTHER: "其他图示",
    ChartType.UNKNOWN: "未知",
}

# Edge-VLM system/user prompt — force a single token-like label.
CLASSIFY_PROMPT = (
    "You are a chart classifier for financial research PDFs. "
    "Look at the image and reply with EXACTLY one label from this list "
    "(lowercase, no punctuation, no explanation):\n"
    "bar | line | pie | scatter | heatmap | framework | flowchart | table | other\n\n"
    "Definitions:\n"
    "- bar: vertical/horizontal bar chart\n"
    "- line: line/area time series chart\n"
    "- pie: pie or donut chart\n"
    "- scatter: scatter plot\n"
    "- heatmap: matrix heat map\n"
    "- framework: multi-panel methodology cards, stages, comparison boxes (NOT a pie)\n"
    "- flowchart: process flow with arrows/nodes\n"
    "- table: grid of rows/columns with numbers/text\n"
    "- other: logo, photo, decorative graphic, or unclear\n\n"
    "Answer with only the label."
)

_BAR_KW = ("柱状", "柱形", "条形图", "histogram", "bar chart")
_LINE_KW = ("折线图", "走势图", "净值曲线", "line chart", "累计收益曲线", "多空累计")
_PIE_KW = ("饼图", "pie chart", "环图", "donut", "占比图")
_FLOW_KW = ("流程", "步骤", "flowchart", "→", "->", "智能体", "奖励反馈", "初始种群")
_FRAME_KW = (
    "演进",
    "路径",
    "阶段",
    "框架",
    "方法论",
    "第一阶段",
    "第二阶段",
    "第三阶段",
    "研究框架",
    "总框架",
)
_TABLE_KW = ("展示名称", "年化收益", "rankic", "icir", "夏普", "最大回撤", "中性化处理")
_NOISE = {"资料来源", "数据来源", "请务必阅读", "chatgpt", "华泰研究", "haitong"}


def parse_vlm_label(raw: str) -> tuple[ChartType, float]:
    """Parse free-form VLM output into (ChartType, confidence)."""
    if not raw:
        return ChartType.UNKNOWN, 0.0
    text = raw.strip().lower()
    # Prefer last non-empty line (chat templates often echo the prompt)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidate = lines[-1] if lines else text
    # Strip common wrappers
    candidate = re.sub(r"^[^a-z]*", "", candidate)
    candidate = candidate.split()[0] if candidate.split() else candidate
    candidate = candidate.strip("`'\".,;:()[]{}")

    aliases = {
        "bar": ChartType.BAR,
        "barchart": ChartType.BAR,
        "column": ChartType.BAR,
        "line": ChartType.LINE,
        "linechart": ChartType.LINE,
        "area": ChartType.LINE,
        "pie": ChartType.PIE,
        "donut": ChartType.PIE,
        "scatter": ChartType.SCATTER,
        "heatmap": ChartType.HEATMAP,
        "heat": ChartType.HEATMAP,
        "framework": ChartType.FRAMEWORK,
        "infographic": ChartType.FRAMEWORK,
        "roadmap": ChartType.FRAMEWORK,
        "flowchart": ChartType.FLOWCHART,
        "flow": ChartType.FLOWCHART,
        "diagram": ChartType.FLOWCHART,
        "table": ChartType.TABLE,
        "other": ChartType.OTHER,
        "unknown": ChartType.UNKNOWN,
    }
    if candidate in aliases:
        return aliases[candidate], 0.85

    # Fuzzy contains
    for key, ctype in aliases.items():
        if key in text and key not in ("flow",):  # avoid over-match
            conf = 0.55 if key in ("other", "unknown") else 0.65
            return ctype, conf

    # Chinese fragments sometimes leak through
    if "柱" in raw:
        return ChartType.BAR, 0.5
    if "折线" in raw or "走势" in raw:
        return ChartType.LINE, 0.5
    if "饼" in raw:
        return ChartType.PIE, 0.5
    if "框架" in raw or "阶段" in raw:
        return ChartType.FRAMEWORK, 0.55
    if "流程" in raw:
        return ChartType.FLOWCHART, 0.55
    if "表" in raw:
        return ChartType.TABLE, 0.45

    return ChartType.UNKNOWN, 0.2


def ocr_prior_from_texts(texts: list[str]) -> tuple[ChartType, float, str]:
    """OCR-only soft classification prior from recognized strings."""
    clean = [t.strip() for t in texts if t and t.strip()]
    clean = [t for t in clean if not any(n in t.lower() for n in _NOISE)]
    if not clean:
        return ChartType.UNKNOWN, 0.0, "no_ocr_text"

    joined = " ".join(clean)
    joined_l = joined.lower()

    def hit(kws: tuple[str, ...]) -> int:
        return sum(1 for k in kws if k in joined or k in joined_l)

    scores: dict[ChartType, float] = {t: 0.0 for t in ChartType}

    # Explicit markers
    if hit(_PIE_KW):
        scores[ChartType.PIE] += 0.9
    if hit(_BAR_KW):
        scores[ChartType.BAR] += 0.9
    if hit(_LINE_KW):
        scores[ChartType.LINE] += 0.85

    # Framework / stages — strong signal for research methodology diagrams
    frame_hits = hit(_FRAME_KW)
    if frame_hits:
        scores[ChartType.FRAMEWORK] += 0.35 * min(frame_hits, 4)
    if re.search(r"第[一二三四五六七八九十\d]+阶段", joined):
        scores[ChartType.FRAMEWORK] += 0.7
    if sum(1 for t in clean if re.search(r"^[1-3][\.、．]", t.strip())) >= 2:
        scores[ChartType.FRAMEWORK] += 0.4

    flow_hits = hit(_FLOW_KW)
    if flow_hits:
        scores[ChartType.FLOWCHART] += 0.3 * min(flow_hits, 3)

    table_hits = hit(_TABLE_KW)
    pct = sum(1 for t in clean if re.search(r"\d+(\.\d+)?%", t))
    if table_hits >= 2 or pct >= 5:
        scores[ChartType.TABLE] += 0.8 + 0.05 * min(table_hits, 4)

    date_count = sum(
        1 for t in clean if re.match(r"^(20\d{2}|\d{2}-\d{2}|\d{4}-\d{2})$", t.strip())
    )
    if date_count >= 3:
        scores[ChartType.LINE] += 0.7

    # Dense text without numeric series → framework/infographic, not pie
    alpha = [t for t in clean if len(t) >= 4 and not re.match(r"^[\d\.%\-\s]+$", t)]
    if len(alpha) >= 10 and scores[ChartType.PIE] < 0.5:
        scores[ChartType.FRAMEWORK] += 0.45

    best = max(scores, key=scores.get)
    conf = min(0.95, scores[best])
    if conf < 0.25:
        return ChartType.UNKNOWN, conf, "weak_ocr"
    return best, conf, f"ocr_score={conf:.2f}"


def ocr_prior_from_lines(lines: list[Any]) -> tuple[ChartType, float, str]:
    texts = [getattr(ln, "text", "") or "" for ln in lines]
    return ocr_prior_from_texts(texts)


def fuse_classification(
    *,
    vlm_type: ChartType | None,
    vlm_confidence: float | None,
    ocr_type: ChartType | None,
    ocr_confidence: float | None,
) -> ChartClassification:
    """Fuse edge-VLM and OCR priors into a final ChartClassification."""
    vlm_type = vlm_type or ChartType.UNKNOWN
    ocr_type = ocr_type or ChartType.UNKNOWN
    vlm_c = float(vlm_confidence or 0.0)
    ocr_c = float(ocr_confidence or 0.0)

    # Case: only one side available
    if vlm_type == ChartType.UNKNOWN and ocr_type != ChartType.UNKNOWN:
        return ChartClassification(
            chart_type=ocr_type,
            confidence=ocr_c * 0.9,
            source="ocr",
            vlm_type=vlm_type if vlm_confidence is not None else None,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale="ocr_only",
        )
    if ocr_type == ChartType.UNKNOWN and vlm_type != ChartType.UNKNOWN:
        return ChartClassification(
            chart_type=vlm_type,
            confidence=vlm_c,
            source="vlm",
            vlm_type=vlm_type,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type if ocr_confidence is not None else None,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale="vlm_only",
        )
    if vlm_type == ChartType.UNKNOWN and ocr_type == ChartType.UNKNOWN:
        return ChartClassification(
            chart_type=ChartType.UNKNOWN,
            confidence=0.0,
            source="fusion",
            vlm_type=vlm_type,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale="both_unknown",
        )

    # Agreement
    if vlm_type == ocr_type:
        conf = min(0.98, 0.5 * vlm_c + 0.5 * ocr_c + 0.15)
        return ChartClassification(
            chart_type=vlm_type,
            confidence=conf,
            source="fusion",
            vlm_type=vlm_type,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale="agree",
        )

    # Known disagreement rules (OCR saves VLM from common pie/framework confusions)
    if vlm_type == ChartType.PIE and ocr_type in (
        ChartType.FRAMEWORK,
        ChartType.FLOWCHART,
        ChartType.TABLE,
    ):
        if ocr_c >= 0.4:
            return ChartClassification(
                chart_type=ocr_type,
                confidence=min(0.9, ocr_c + 0.1),
                source="fusion",
                vlm_type=vlm_type,
                vlm_confidence=vlm_confidence,
                ocr_type=ocr_type,
                ocr_confidence=ocr_confidence,
                labels_considered=[t.value for t in CHART_TYPE_LABELS],
                rationale="override_pie_with_ocr_structure",
            )

    if ocr_type == ChartType.TABLE and ocr_c >= 0.7 and vlm_type not in (
        ChartType.TABLE,
        ChartType.BAR,
    ):
        return ChartClassification(
            chart_type=ChartType.TABLE,
            confidence=ocr_c,
            source="fusion",
            vlm_type=vlm_type,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale="ocr_table_wins",
        )

    # Near-synonyms: framework ↔ flowchart (methodology cards vs pure flow)
    structure_pair = {ChartType.FRAMEWORK, ChartType.FLOWCHART}
    if vlm_type in structure_pair and ocr_type in structure_pair:
        # Prefer higher confidence; tie-break to OCR (Chinese labels more reliable)
        if ocr_c >= vlm_c:
            pick, conf, why = ocr_type, ocr_c, "structure_pair_ocr"
        else:
            pick, conf, why = vlm_type, vlm_c, "structure_pair_vlm"
        return ChartClassification(
            chart_type=pick,
            confidence=float(conf),
            source="fusion",
            vlm_type=vlm_type,
            vlm_confidence=vlm_confidence,
            ocr_type=ocr_type,
            ocr_confidence=ocr_confidence,
            labels_considered=[t.value for t in CHART_TYPE_LABELS],
            rationale=why,
        )

    # Weighted pick
    if vlm_c >= ocr_c + 0.15:
        pick, conf, why = vlm_type, vlm_c, "vlm_higher"
        src = "fusion"
    elif ocr_c >= vlm_c + 0.15:
        pick, conf, why = ocr_type, ocr_c, "ocr_higher"
        src = "fusion"
    else:
        # Prefer structured diagram types over pie/other when close
        priority = {
            ChartType.FRAMEWORK: 3,
            ChartType.FLOWCHART: 3,
            ChartType.TABLE: 3,
            ChartType.LINE: 2,
            ChartType.BAR: 2,
            ChartType.SCATTER: 2,
            ChartType.HEATMAP: 2,
            ChartType.PIE: 1,
            ChartType.OTHER: 0,
            ChartType.UNKNOWN: 0,
        }
        p_ocr = priority.get(ocr_type, 0)
        p_vlm = priority.get(vlm_type, 0)
        if p_ocr > p_vlm:
            pick, conf, why = ocr_type, max(ocr_c, 0.45), "priority_ocr"
        elif p_vlm > p_ocr:
            pick, conf, why = vlm_type, max(vlm_c, 0.45), "priority_vlm"
        elif ocr_c >= vlm_c:
            pick, conf, why = ocr_type, max(ocr_c, 0.45), "tie_ocr_conf"
        else:
            pick, conf, why = vlm_type, max(vlm_c, 0.45), "tie_vlm_conf"
        src = "fusion"

    return ChartClassification(
        chart_type=pick,
        confidence=float(conf),
        source=src,  # type: ignore[arg-type]
        vlm_type=vlm_type,
        vlm_confidence=vlm_confidence,
        ocr_type=ocr_type,
        ocr_confidence=ocr_confidence,
        labels_considered=[t.value for t in CHART_TYPE_LABELS],
        rationale=why,
    )
