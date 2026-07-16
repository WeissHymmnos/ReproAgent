"""Post-process markdown/HTML tables with semantic labels.

Heuristic classification of financial statement tables into statement types
(income_statement, balance_sheet, cash_flow) and detection of header rows
and total rows. Operates on already-extracted markdown table text from
upstream backends (PaddleStructure, MinerU, etc.) — does NOT reimplement
table structure detection.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finreportparser.types import PageBlock

logger = logging.getLogger(__name__)

_INCOME_KEYWORDS: list[str] = [
    "营业收入", "营业总收入", "主营业务收入", "营收",
    "营业成本", "主营业务成本", "营业总成本",
    "毛利", "毛利率", "销售毛利率",
    "营业利润", "利润总额", "净利润", "归母净利润", "扣非净利润",
    "净利率", "销售净利率",
    "基本每股收益", "稀释每股收益", "每股收益",
    "销售费用", "管理费用", "研发费用", "财务费用", "期间费用",
    "EBIT", "EBITDA",
]

_BALANCE_SHEET_KEYWORDS: list[str] = [
    "资产总计", "资产总额", "总资产",
    "负债总计", "负债总额", "总负债",
    "所有者权益合计", "股东权益合计", "净资产", "归母净资产",
    "流动资产合计", "非流动资产合计",
    "流动负债合计", "非流动负债合计",
    "货币资金", "应收账款", "存货", "固定资产", "无形资产", "商誉",
    "短期借款", "长期借款", "应付账款",
    "资产负债率", "流动比率", "速动比率", "产权比率",
]

_CASH_FLOW_KEYWORDS: list[str] = [
    "经营活动现金流", "经营活动产生的现金流量净额", "经营活动现金流量净额",
    "投资活动现金流", "投资活动产生的现金流量净额", "投资活动现金流量净额",
    "筹资活动现金流", "筹资活动产生的现金流量净额", "筹资活动现金流量净额",
    "现金净增加额", "现金及现金等价物净增加额",
    "期末现金余额", "期末现金及现金等价物余额",
    "自由现金流", "FCF",
    "现金流量表",
]

# Duplicated from quality.py to avoid circular import.
_TOTAL_KEYWORDS: list[str] = [
    "合计", "总计", "总额", "小计",
    "total", "sum", "subtotal",
]

# Matches markdown table separator lines like |---|---| or |:---:|---|
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s\-:|]+\|?\s*$")


@dataclass
class TableSemantics:
    """Semantic labels for a single table."""

    statement_type: str = "unknown"
    header_row_indices: list[int] = field(default_factory=list)
    total_row_indices: list[int] = field(default_factory=list)
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_markdown_rows(markdown: str) -> list[list[str]]:
    if not markdown:
        return []
    rows: list[list[str]] = []
    for line in markdown.strip().split("\n"):
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        if _SEPARATOR_RE.match(stripped):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if cells:
            rows.append(cells)
    return rows


def _is_separator_line(line: str) -> bool:
    return bool(_SEPARATOR_RE.match(line.strip()))


def _is_total_row(cells: list[str]) -> bool:
    for cell in cells:
        cell_lower = cell.lower()
        for kw in _TOTAL_KEYWORDS:
            if kw in cell_lower:
                return True
    return False


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

def _detect_header_row(rows: list[list[str]]) -> list[int]:
    if not rows:
        return []

    best_score = -1
    best_idx = 0

    for i, row in enumerate(rows[:5]):
        score = 0
        for cell in row:
            cell_str = cell.strip()
            if not cell_str:
                continue

            if _YEAR_RE.search(cell_str):
                score += 2
            if "年" in cell_str:
                score += 1
            if any(unit in cell_str for unit in ["亿元", "万元", "%"]):
                score += 1
            if any(kw in cell_str for kw in ["指标", "项目", "科目"]):
                score += 2

        if score > best_score:
            best_score = score
            best_idx = i

    if best_score >= 2:
        return [best_idx]

    return [0]


def _score_statement_type(
    rows: list[list[str]],
) -> tuple[str, float, list[str]]:
    all_text = " ".join(cell for row in rows for cell in row)

    scores: dict[str, tuple[int, list[str]]] = {
        "income_statement": (0, []),
        "balance_sheet": (0, []),
        "cash_flow": (0, []),
    }

    keyword_map = {
        "income_statement": _INCOME_KEYWORDS,
        "balance_sheet": _BALANCE_SHEET_KEYWORDS,
        "cash_flow": _CASH_FLOW_KEYWORDS,
    }

    for stmt_type, keywords in keyword_map.items():
        score, matched = scores[stmt_type]
        for kw in keywords:
            if kw in all_text:
                score += 1
                matched.append(kw)
        scores[stmt_type] = (score, matched)

    best_type = max(scores, key=lambda k: scores[k][0])
    best_score, best_matched = scores[best_type]

    if best_score == 0:
        return "unknown", 0.0, []

    total_nonzero = sum(1 for s in scores.values() if s[0] > 0)
    if total_nonzero == 0:
        return "unknown", 0.0, []

    # Confidence: diminishing-returns curve — 1 match ~0.5, 2 ~0.75, 5+ ~1.0.
    # Penalised when multiple statement types match (ambiguous table).
    base = min(best_score / 5.0, 1.0)

    if total_nonzero == 1:
        confidence = min(0.5 + base * 0.5, 1.0)
    else:
        second_best = sorted(scores.values(), key=lambda x: x[0], reverse=True)[1][0]
        if second_best > 0:
            confidence = base * (best_score / (best_score + second_best))
        else:
            confidence = base

    confidence = max(confidence, 0.3) if best_score > 0 else 0.0

    return best_type, round(confidence, 3), best_matched


def classify_table(markdown: str) -> TableSemantics:
    """Classify a markdown table and return semantic labels.

    Returns a TableSemantics with statement_type, header/total row indices,
    confidence, and matched keywords. Empty or unparseable input returns
    statement_type="unknown" with confidence=0.0.
    """
    if not markdown or not markdown.strip():
        return TableSemantics()

    rows = _parse_markdown_rows(markdown)
    if not rows:
        return TableSemantics()

    header_row_indices = _detect_header_row(rows)

    total_row_indices: list[int] = []
    for i, row_cells in enumerate(rows):
        if _is_total_row(row_cells):
            total_row_indices.append(i)

    statement_type, confidence, matched_keywords = _score_statement_type(rows)

    return TableSemantics(
        statement_type=statement_type,
        header_row_indices=header_row_indices,
        total_row_indices=total_row_indices,
        confidence=confidence,
        matched_keywords=matched_keywords,
        row_count=len(rows),
        col_count=len(rows[0]) if rows else 0,
    )


def annotate_block(block: PageBlock) -> PageBlock:
    """Soft-attach table semantics to a PageBlock's metadata.

    Writes ``block.metadata["table_semantics"]`` with the classification
    result. Non-TABLE blocks or blocks without text are returned unchanged.
    Never raises on parse failures.
    """
    from finreportparser.types import BlockType

    if block.type != BlockType.TABLE:
        return block

    if not block.text:
        return block

    try:
        sem = classify_table(block.text)
        if block.metadata is None:
            block.metadata = {}
        block.metadata["table_semantics"] = sem.to_dict()
    except Exception as exc:
        logger.warning("Failed to classify table semantics: %s", exc)

    return block


def annotate_pages(pages: list[Any]) -> list[Any]:
    """Annotate all TABLE blocks across a list of PageResult objects."""
    from finreportparser.types import BlockType

    for page in pages:
        for block in page.blocks:
            if block.type == BlockType.TABLE:
                annotate_block(block)
    return pages