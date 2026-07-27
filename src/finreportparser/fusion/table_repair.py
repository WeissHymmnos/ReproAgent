"""Robust table GFM repair for OCR/structure extraction errors.

Operates *generically* on any Chinese financial-research style table —
not document-specific hardcodes. Goals:

1. Detect glued multi-metric headers (OCR merged several columns into one cell)
2. Split headers via known metric-token lexicon + greedy match
3. Phrase-level OCR confusable corrections (温价→溢价, 讨级→评级, …)
4. Realign row column counts to the header width
5. Prefer higher-quality repaired form when heuristics fire

Called after structure extraction, before ``is_acceptable_table``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Lexicon: metric / field tokens commonly used as table headers in research PDFs
# Ordered longest-first for greedy matching.
# ---------------------------------------------------------------------------
_HEADER_TOKENS: tuple[str, ...] = tuple(
    sorted(
        {
            "展示名称",
            "因子名称",
            "中性化处理",
            "年化收益率",
            "年化波动率",
            "最大回撤",
            "夏普比率",
            "信息比率",
            "卡玛比率",
            "因子IC",
            "RankIC",
            "ICIR",
            "RankICIR",
            "超额收益",
            "年化超额",
            "累计收益",
            "胜率",
            "换手率",
            "样本数",
            "t值",
            "P值",
            "置信度",
            "分组",
            "多空收益",
            "做多收益",
            "做空收益",
            "2022年收益",
            "2023年收益",
            "2024年收益",
            "2025年收益",
            "2026年收益",
            "名称",
            "代码",
            "评级",
            "期限",
            "规模",
        },
        key=len,
        reverse=True,
    )
)

# Phrase-level OCR confusions (wrong → correct). Prefer longer phrases first.
# Covers common PP-OCR / low-res confusions in Chinese financial text.
_OCR_PHRASE_FIXES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            # premium / yield
            ("纯温价率", "纯债溢价率"),
            ("纯量温价率", "纯债溢价率"),
            ("平价温价率", "平价溢价率"),
            ("转股温价率", "转股溢价率"),
            ("种股温价率", "转股溢价率"),
            ("温价率", "溢价率"),
            ("温价", "溢价"),
            # rating / remaining
            # Full-form rating phrases only (never bare 信用评 / 用评 — chain-corrupt)
            ("信用评级级级", "信用评级"),
            ("信用评级级", "信用评级"),
            ("信评级级", "信用评级"),
            ("信用评线", "信用评级"),
            ("信同评级", "信用评级"),
            ("信用评机", "信用评级"),
            ("信用评规", "信用评级"),
            ("讨级", "评级"),
            # bare 评线 only when not already 评级
            ("制余期限", "剩余期限"),
            ("到余期限", "剩余期限"),
            ("到金期限", "剩余期限"),
            ("制金期限", "剩余期限"),
            ("制余期", "剩余期限"),
            ("刺余期限", "剩余期限"),
            ("时金期", "剩余期限"),
            # returns / drawdown / sharpe
            ("年化收孟率", "年化收益率"),
            ("年化益", "年化收益"),
            ("平化波暗率", "年化波动率"),
            ("年化成动率", "年化波动率"),
            ("最大W撒", "最大回撤"),
            ("最大四根", "最大回撤"),
            ("最大四", "最大回撤"),
            ("最大更普", "最大回撤"),
            ("夏晋比率", "夏普比率"),
            ("更普比", "夏普比率"),
            # IC / excess
            ("因于IC", "因子IC"),
            ("园手IC", "因子IC"),
            ("国于IC", "因子IC"),
            ("RankiC", "RankIC"),
            ("RkC", "RankIC"),
            ("超收盖", "超额收益"),
            ("超收益", "超额收益"),
            ("超收", "超额收益"),
            # factor names
            ("绝时价格", "绝对价格"),
            ("市信园子", "市值因子"),
            ("小市国子", "小市值因子"),
            ("PB体值因子", "PB估值因子"),
            ("PE体值因子", "PE估值因子"),
            ("体值因子", "估值因子"),
            ("高ROE国子", "高ROE因子"),
            ("股量20", "正股动量20"),
            ("点股", "正股"),
            ("孟股市值", "正股市值"),
            ("正联市值", "正股市值"),
            ("美联市保", "正股市值"),
            ("股市保", "正股市值"),
            ("直股审值", "正股市值"),
            ("点股审值", "正股市值"),
            ("点提波储率", "正股波动率"),
            ("点股波储率", "正股波动率"),
            ("止股波动率", "正股波动率"),
            ("具股发硅率", "正股波动率"),
            # trading volume / turnover
            ("成交提", "成交额"),
            ("成交程", "成交额"),
            ("成交相", "成交额"),
            ("成文额", "成交额"),
            ("点文", "成交额"),
            ("提手单", "换手率"),
            ("提导率", "换手率"),
            ("换手车", "换手率"),
            ("换导车", "换手率"),
            # bond-related
            ("转绩余额", "转债余额"),
            ("转缓余额", "转债余额"),
            ("转侵余程", "转债余额"),
            ("转值余额", "转债余额"),
            ("转慢余额", "转债余额"),
            ("转续余额", "转债余额"),
            ("种续余额", "转债余额"),
            ("种缓余额", "转债余额"),
            ("量金提", "转债余额"),
            ("便余", "转债余额"),
            ("特债价格", "转债价格"),
            ("种值价格", "转债价格"),
            ("特续价路", "转债价格"),
            ("特值价", "转债价格"),
            ("转债价品", "转债价格"),
            ("转提价格", "转债价格"),
            ("种续价格", "转债价格"),
            ("债底距离", "债底距离"),
            ("成距离", "债底距离"),
            # operators / greek
            ("Delta 待守", "Delta防守"),
            ("Delta待守", "Delta防守"),
            ("Dea", "Delta"),
            ("Dela", "Delta"),
            ("Deta", "Delta"),
            ("Da，", "Delta、"),
            # misc quality phrases
            ("平价品缩质量", "平价压缩质量"),
            ("温价品缩质量", "溢价压缩质量"),
            ("平价领光质量", "平价领先质量"),
            ("点股领光质量", "正股领先质量"),
            ("温价中枢趋势", "溢价中枢趋势"),
            ("均值特复", "均值修复"),
            ("短期偏高反转", "短期偏离反转"),
            ("低点400反转", "低点40日反转"),
            ("20 日反时", "20日反转"),
            ("隐金波动率", "隐含波动率"),
            ("稳含波动率", "隐含波动率"),
            ("规期波动率", "短期波动率"),
            ("规期波始率", "短期波动率"),
            ("中期偏离反5/60", "短中期偏离反转5/60"),
            ("10日益减MA10", "10日收益减MA10"),
            ("低金", "低余额"),
            ("纯量温价率因于", "纯债溢价率因子"),
            ("纯温价率因子", "纯债溢价率因子"),
            ("园子", "因子"),
            ("国子", "因子"),
            ("因于", "因子"),
        ],
        key=lambda x: len(x[0]),
        reverse=True,
    )
)

# Glued-header fingerprint: one fat cell that looks like several metrics smashed together
_GLUE_HINTS = (
    "年化收益",
    "年化波动",
    "最大回",
    "夏普",
    "RankIC",
    "因子IC",
    "超额",
    "收孟",
    "波暗",
    "W撒",
)


@dataclass
class TableRepairResult:
    gfm: str
    repaired: bool
    actions: list[str]


def _parse_gfm_rows(gfm: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in gfm.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # separator
        if cells and all(re.match(r"^:?-+:?$", c or "-") for c in cells):
            rows.append(["---"] * len(cells))
            continue
        rows.append(cells)
    return rows


def _rows_to_gfm(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(row) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * len(row)) + " |")
    # If original had separator as row[1] we already emit one after header
    # Drop accidental double separators
    out = []
    prev_sep = False
    for line in lines:
        is_sep = bool(re.match(r"^\|\s*---", line))
        if is_sep and prev_sep:
            continue
        out.append(line)
        prev_sep = is_sep
    return "\n".join(out)


def apply_ocr_phrase_fixes(text: str) -> str:
    """Apply phrase-level OCR corrections (longest match first)."""
    if not text:
        return text
    out = text
    for wrong, right in _OCR_PHRASE_FIXES:
        if wrong in out:
            out = out.replace(wrong, right)
    # Isolated 评线 (not already 评级)
    out = re.sub(r"(?<!评)评线", "评级", out)
    # Collapse residual 信用评级级…
    out = re.sub(r"信用评级级+", "信用评级", out)
    out = re.sub(r"信评级级+", "信用评级", out)
    # Numeric punctuation OCR: 1,16 → 1.16 when it looks like a ratio
    out = re.sub(r"\b(\d),(\d{2})\b", r"\1.\2", out)
    return out


def _greedy_split_header(blob: str) -> list[str] | None:
    """Greedy longest-token match to split a glued header string."""
    s = re.sub(r"\s+", "", blob)
    if len(s) < 6:
        return None
    # Normalize common OCR mess before matching
    s = apply_ocr_phrase_fixes(s)
    # Extra soft fixes for glued-only forms
    s = (
        s.replace("年化收孟率", "年化收益率")
        .replace("平化波暗率", "年化波动率")
        .replace("年化成动率", "年化波动率")
        .replace("最大W撒", "最大回撤")
        .replace("因于IC", "因子IC")
        .replace("超收盖", "超额收益")
        .replace("超收益", "超额收益")
    )

    parts: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        matched = False
        for tok in _HEADER_TOKENS:
            if s.startswith(tok, i):
                parts.append(tok)
                i += len(tok)
                matched = True
                break
        if matched:
            continue
        # skip junk punctuation between tokens
        if s[i] in "、，,./;；:：|·• ":
            i += 1
            continue
        # unknown fragment: absorb until next known token
        j = i + 1
        while j < n:
            if any(s.startswith(tok, j) for tok in _HEADER_TOKENS):
                break
            j += 1
        frag = s[i:j]
        if frag and frag not in ("的", "与", "及"):
            # drop pure OCR garbage fragments under 2 chars unless alphanumeric
            if len(frag) >= 2 or re.match(r"^[A-Za-z0-9%]+$", frag):
                parts.append(frag)
        i = j

    # Need at least 3 recovered columns to be useful
    if len(parts) < 3:
        return None
    return parts


def header_looks_glued(header: list[str]) -> bool:
    """True if header has one oversized cell that likely merged several metrics."""
    if not header:
        return False
    non_empty = [c for c in header if c and c != "---"]
    if not non_empty:
        return False
    # Classic failure: many empty cells + one fat cell
    empty = sum(1 for c in header if not c)
    fat = [c for c in header if len(re.sub(r"\s+", "", c)) >= 12]
    if fat and empty >= 2:
        blob = max(fat, key=len)
        if any(h in blob for h in _GLUE_HINTS):
            return True
    # Or single cell containing multiple metric keywords
    for c in non_empty:
        hits = sum(1 for h in _GLUE_HINTS if h in c)
        if hits >= 2 and len(re.sub(r"\s+", "", c)) >= 10:
            return True
    return False


def _median_data_cols(rows: list[list[str]]) -> int:
    data = [r for r in rows[2:] if r and not all(c == "---" for c in r)]
    if not data:
        data = [r for r in rows[1:] if r and not all(re.match(r"^:?-+:?$", c or "") for c in r)]
    lengths = [len([c for c in r if True]) for r in data]
    if not lengths:
        return len(rows[0]) if rows else 0
    lengths.sort()
    return lengths[len(lengths) // 2]


def _pad_or_trim(row: list[str], n: int) -> list[str]:
    if len(row) == n:
        return row
    if len(row) > n:
        # Merge overflow into last cell rather than drop numbers
        head, tail = row[: n - 1], row[n - 1 :]
        return head + [" ".join(tail)]
    return row + [""] * (n - len(row))


def _split_merged_numeric_cell(cell: str) -> list[str] | None:
    """Split '13.41% -17.69%' style merges into two cells."""
    cell = cell.strip()
    # two percentages/numbers separated by space
    m = re.match(
        r"^([+-]?\d+(?:\.\d+)?%?)\s+([+-]?\d+(?:\.\d+)?%?)$",
        cell,
    )
    if m:
        return [m.group(1), m.group(2)]
    return None


def repair_data_row_merges(row: list[str], target_cols: int) -> list[str]:
    """Expand merged numeric cells; fill empty slots from adjacent merges.

    Handles: ``9.07% |  | 12.29% -16.33% | …`` → ``9.07% | 12.29% | -16.33% | …``
    without first blindly splitting (which would overshoot column count).
    """
    # Prefer empty-slot absorption before blind expand
    fixed: list[str] = []
    i = 0
    while i < len(row):
        cell = row[i]
        # num | "" | "a b"  → num | a | b
        if (
            i + 2 < len(row)
            and row[i + 1] == ""
            and _split_merged_numeric_cell(row[i + 2])
        ):
            parts = _split_merged_numeric_cell(row[i + 2])
            assert parts is not None
            fixed.append(cell)
            fixed.extend(parts)
            i += 3
            continue
        # "" | "a b" → a | b
        if cell == "" and i + 1 < len(row) and _split_merged_numeric_cell(row[i + 1]):
            parts = _split_merged_numeric_cell(row[i + 1])
            assert parts is not None
            fixed.extend(parts)
            i += 2
            continue
        # plain "a b" only when we're still short of target
        parts = _split_merged_numeric_cell(cell)
        if parts and len(fixed) + len(parts) + (len(row) - i - 1) <= target_cols:
            fixed.extend(parts)
        else:
            fixed.append(cell)
        i += 1

    return _pad_or_trim(fixed, target_cols)


def repair_table_gfm(gfm: str) -> TableRepairResult:
    """Main entry: return repaired GFM + audit trail."""
    if not gfm or not gfm.strip():
        return TableRepairResult(gfm=gfm or "", repaired=False, actions=[])

    actions: list[str] = []
    rows = _parse_gfm_rows(gfm)
    if len(rows) < 2:
        fixed = apply_ocr_phrase_fixes(gfm)
        return TableRepairResult(
            gfm=fixed,
            repaired=fixed != gfm,
            actions=["phrase_fix"] if fixed != gfm else [],
        )

    # Drop separator rows from logical processing; rebuild later
    header = [apply_ocr_phrase_fixes(c) for c in rows[0]]
    if header != rows[0]:
        actions.append("header_phrase_fix")

    data_rows: list[list[str]] = []
    for r in rows[1:]:
        if r and all(c == "---" or re.match(r"^:?-+:?$", c or "") for c in r):
            continue
        fixed_r = [apply_ocr_phrase_fixes(c) for c in r]
        if fixed_r != r:
            actions.append("body_phrase_fix")
        data_rows.append(fixed_r)

    # --- Glued header split ---
    if header_looks_glued(header):
        # Prefer splitting the fattest cell; keep leading name columns
        fat_idx = max(range(len(header)), key=lambda i: len(header[i] or ""))
        leading = [c for c in header[:fat_idx] if c]
        trailing = [c for c in header[fat_idx + 1 :] if c]
        split = _greedy_split_header(header[fat_idx])
        if split:
            new_header = leading + split + trailing
            # Deduplicate accidental doubles
            deduped: list[str] = []
            for h in new_header:
                if not deduped or deduped[-1] != h:
                    deduped.append(h)
            header = deduped
            actions.append(f"split_glued_header→{len(header)}cols")

    # If still weak header but data is wide, synthesize metric headers from lexicon
    median_cols = _median_data_cols([header] + data_rows) if data_rows else len(header)
    non_empty_h = [c for c in header if c]
    if len(non_empty_h) <= 3 and median_cols >= 6:
        # Try splitting concatenation of all header cells
        blob = "".join(non_empty_h)
        split = _greedy_split_header(blob)
        if split and len(split) >= median_cols - 1:
            header = split[:median_cols] if len(split) >= median_cols else split
            actions.append("resplit_header_blob")

    target_cols = max(len(header), median_cols)
    # Prefer header length when we successfully split
    if "split_glued_header" in "".join(actions) or "resplit_header_blob" in "".join(actions):
        target_cols = len(header)

    header = _pad_or_trim(header, target_cols)
    fixed_data = [repair_data_row_merges(r, target_cols) for r in data_rows]
    if any(len(r) != target_cols for r in data_rows):
        actions.append(f"realign_cols→{target_cols}")

    # Rebuild GFM
    all_rows = [header] + fixed_data
    new_gfm = _rows_to_gfm(all_rows)

    # Final phrase pass on whole string (catches residuals)
    final = apply_ocr_phrase_fixes(new_gfm)
    if final != new_gfm:
        actions.append("final_phrase_fix")
        new_gfm = final

    repaired = bool(actions) and new_gfm.strip() != gfm.strip()
    return TableRepairResult(gfm=new_gfm, repaired=repaired, actions=list(dict.fromkeys(actions)))
