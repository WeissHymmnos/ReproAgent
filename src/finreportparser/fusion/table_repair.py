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
            "2022年益",  # OCR truncated
            "名称",
            "代码",
            "评级",
            "期限",
            "规模",
            "卡玛比率",
            "卡比率",
        },
        key=len,
        reverse=True,
    )
)

# Canonical factor-backtest header (most common research layout)
_STANDARD_FACTOR_HEADERS: tuple[str, ...] = (
    "展示名称",
    "中性化处理",
    "年化收益率",
    "年化波动率",
    "最大回撤",
    "夏普比率",
    "因子IC",
    "RankIC",
    "超额收益",
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
            ("最大W", "最大回撤"),
            ("最大四根", "最大回撤"),
            ("最大四", "最大回撤"),
            ("最大更普", "最大回撤"),
            ("诗级", "评级"),
            ("讨载", "评级"),
            ("诗间", "评级"),
            ("售合波动率", "隐含波动率"),
            ("正胶波动率", "正股波动率"),
            ("短期收通动量", "短期收益动量"),
            ("夏晋比率", "夏普比率"),
            ("更普比", "夏普比率"),
            ("最大重普", "最大回撤"),
            ("卡比率", "卡玛比率"),
            ("图子名称", "因子名称"),
            ("2022年益", "2022年收益"),
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
    # 子IC → 因子IC but never touch 因子IC (lookbehind)
    out = re.sub(r"(?<!因)子IC", "因子IC", out)
    out = re.sub(r"因因子IC", "因子IC", out)
    # Collapse residual 信用评级级…
    out = re.sub(r"信用评级级+", "信用评级", out)
    out = re.sub(r"信评级级+", "信用评级", out)
    # Numeric punctuation OCR: 1,16 → 1.16 when it looks like a ratio
    out = re.sub(r"\b(\d),(\d{2})\b", r"\1.\2", out)
    return out


def _greedy_split_header(blob: str, *, min_parts: int = 2) -> list[str] | None:
    """Greedy longest-token match to split a glued header string."""
    s = re.sub(r"\s+", "", blob)
    if len(s) < 4:
        return None
    # Normalize common OCR mess before matching
    s = apply_ocr_phrase_fixes(s)
    # Extra soft fixes for glued-only forms
    s = (
        s.replace("年化收孟率", "年化收益率")
        .replace("平化波暗率", "年化波动率")
        .replace("年化成动率", "年化波动率")
        .replace("最大W撒", "最大回撤")
        .replace("最大重普", "最大回撤")
        .replace("因于IC", "因子IC")
        .replace("超收盖", "超额收益")
        .replace("超收益", "超额收益")
        .replace("子IC", "因子IC")
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

    if len(parts) < min_parts:
        return None
    return parts


def _cell_is_multi_metric(cell: str) -> bool:
    """True if a single header cell contains ≥2 known metric tokens."""
    if not cell or len(cell) < 6:
        return False
    fixed = apply_ocr_phrase_fixes(cell)
    if "|" in fixed:
        return True
    hits = sum(1 for tok in _HEADER_TOKENS if tok in fixed and len(tok) >= 3)
    # also glue hints
    hits += sum(1 for h in _GLUE_HINTS if h in fixed)
    return hits >= 2 or (len(re.sub(r"\s+", "", fixed)) >= 10 and hits >= 1)


def header_looks_glued(header: list[str]) -> bool:
    """True if header has cells that likely merged several metrics."""
    if not header:
        return False
    non_empty = [c for c in header if c and c != "---"]
    if not non_empty:
        return False
    if any(_cell_is_multi_metric(c) for c in non_empty):
        return True
    # Classic failure: many empty cells + one fat cell
    empty = sum(1 for c in header if not c)
    fat = [c for c in header if len(re.sub(r"\s+", "", c)) >= 12]
    if fat and empty >= 2:
        blob = max(fat, key=len)
        if any(h in blob for h in _GLUE_HINTS):
            return True
    return False


def _expand_header_cells(header: list[str]) -> list[str]:
    """Split *every* multi-metric header cell; drop empties; de-dupe adjacent."""
    expanded: list[str] = []
    for cell in header:
        if not cell or cell == "---":
            continue
        if _cell_is_multi_metric(cell):
            split = _greedy_split_header(cell, min_parts=2)
            if split:
                expanded.extend(split)
                continue
        expanded.append(apply_ocr_phrase_fixes(cell))
    # de-dupe consecutive identical headers (OCR double-read)
    deduped: list[str] = []
    for h in expanded:
        if deduped and deduped[-1] == h:
            continue
        # drop exact later duplicates of RankIC/因子IC when consecutive pattern broken
        deduped.append(h)
    # collapse non-adjacent exact duplicate metric tails (e.g. RankIC ... RankIC)
    seen: set[str] = set()
    final: list[str] = []
    for h in deduped:
        key = h.lower()
        if key in ("rankic", "因子ic", "icir", "rankicir") and key in seen:
            continue
        if key in ("rankic", "因子ic", "icir", "rankicir"):
            seen.add(key)
        final.append(h)
    return final


def _maybe_standard_factor_header(header: list[str], data_cols: int) -> list[str] | None:
    """If row shape matches classic factor table, force canonical headers."""
    if data_cols < 8 or data_cols > 12:
        return None
    blob = "".join(header)
    signals = ("年化", "回撤", "夏普", "RankIC", "超额", "展示名称", "因子", "中性化")
    if sum(1 for s in signals if s in blob) < 3:
        return None
    # Prefer 9-col canonical layout (most common); wider data still maps to 9
    # and body realign will pad/trim.
    if data_cols in (8, 9, 10):
        if data_cols == 8 and "中性化" not in blob:
            return [
                "展示名称",
                "年化收益率",
                "年化波动率",
                "最大回撤",
                "夏普比率",
                "因子IC",
                "RankIC",
                "超额收益",
            ]
        return list(_STANDARD_FACTOR_HEADERS)
    return None


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
    """Split glued numeric cells into two values.

    Handles:
      - ``13.41% -17.69%`` (space-separated)
      - ``7.24%10.11%`` (no separator, common OCR glue)
      - ``8.08%12.83%``
    """
    cell = cell.strip()
    # two percentages/numbers separated by space
    m = re.match(
        r"^([+-]?\d+(?:\.\d+)?%?)\s+([+-]?\d+(?:\.\d+)?%?)$",
        cell,
    )
    if m:
        return [m.group(1), m.group(2)]
    # glued percentages without separator
    m = re.match(
        r"^([+-]?\d+(?:\.\d+)?%)([+-]?\d+(?:\.\d+)?%)$",
        cell,
    )
    if m:
        return [m.group(1), m.group(2)]
    return None


def _split_all_numbers(cell: str) -> list[str] | None:
    """Split a cell into all numeric tokens if ≥2 numbers present."""
    cell = (cell or "").strip()
    if not cell:
        return None
    parts = re.findall(r"[+-]?\d+(?:\.\d+)?%?", cell)
    if len(parts) >= 2 and "".join(parts) == re.sub(r"[\s,，、;/|]+", "", cell):
        return parts
    # also allow separators between numbers
    if len(parts) >= 2 and re.fullmatch(
        r"[+-]?\d+(?:\.\d+)?%?(?:\s+[+-]?\d+(?:\.\d+)?%?)+", cell
    ):
        return parts
    return _split_merged_numeric_cell(cell)


def repair_data_row_merges(row: list[str], target_cols: int) -> list[str]:
    """Expand merged numeric cells and drop empty placeholders to hit *target_cols*.

    Handles: ``9.07% |  | 12.29% -16.33% | …`` → ``9.07% | 12.29% | -16.33% | …``
    and multi-value cells like ``1.17 7.24%``.
    """
    cells = list(row)

    # 1) Drop empty placeholders first so multi-value cells can expand into
    # the freed slots (common text-layer misalignment).
    nonempty = [c for c in cells if c != ""]
    # Estimate expandable numeric tokens
    token_count = 0
    for c in nonempty:
        parts = _split_all_numbers(c)
        token_count += len(parts) if parts else 1
    if token_count >= target_cols and len(nonempty) < len(cells):
        cells = nonempty
    elif len(cells) > target_cols:
        while len(cells) > target_cols and "" in cells:
            cells.remove("")

    # 2) Iteratively expand multi-value numeric cells while under target
    changed = True
    guard = 0
    while changed and guard < 16:
        guard += 1
        changed = False
        next_cells: list[str] = []
        for idx, cell in enumerate(cells):
            remaining_after = len(cells) - idx - 1
            parts = _split_all_numbers(cell)
            if parts and len(next_cells) + len(parts) + remaining_after <= target_cols:
                next_cells.extend(parts)
                if len(parts) > 1:
                    changed = True
            else:
                next_cells.append(cell)
        cells = next_cells

    while len(cells) > target_cols and "" in cells:
        cells.remove("")

    return _pad_or_trim(cells, target_cols)


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

    def _nonempty_count(r: list[str]) -> int:
        return sum(1 for c in r if c and c != "---")

    def _looks_like_header_row(r: list[str]) -> bool:
        blob = "".join(r)
        keys = ("展示名称", "因子名称", "年化", "中性化", "RankIC", "超额", "最大回撤", "夏普")
        return sum(1 for k in keys if k in blob) >= 2 or any(
            _cell_is_multi_metric(c) for c in r if c
        )

    # Drop separator rows
    body = [
        r
        for r in rows
        if not (r and all(c == "---" or re.match(r"^:?-+:?$", c or "") for c in r))
    ]
    if len(body) < 2:
        fixed = apply_ocr_phrase_fixes(gfm)
        return TableRepairResult(gfm=fixed, repaired=fixed != gfm, actions=[])

    # Skip title/caption rows mistaken as header (e.g. "图表5：主要单因子…")
    header_idx = 0
    if (
        len(body) >= 3
        and _nonempty_count(body[0]) <= 3
        and _looks_like_header_row(body[1])
        and not _looks_like_header_row(body[0])
    ):
        header_idx = 1
        actions.append("skip_title_row")

    header = [apply_ocr_phrase_fixes(c) for c in body[header_idx]]
    if header != body[header_idx]:
        actions.append("header_phrase_fix")

    data_rows: list[list[str]] = []
    for r in body[header_idx + 1 :]:
        fixed_r = [apply_ocr_phrase_fixes(c) for c in r]
        if fixed_r != r:
            actions.append("body_phrase_fix")
        data_rows.append(fixed_r)

    median_cols = _median_data_cols([header] + data_rows) if data_rows else len(header)

    # --- Expand multi-metric cells across the whole header row ---
    if header_looks_glued(header) or any(_cell_is_multi_metric(c) for c in header if c):
        expanded = _expand_header_cells(header)
        if len(expanded) > len([c for c in header if c]):
            header = expanded
            actions.append(f"expand_header_cells→{len(header)}cols")

    # Full-blob resplit when still weak
    non_empty_h = [c for c in header if c]
    if len(non_empty_h) <= 4 and median_cols >= 6:
        blob = "".join(non_empty_h)
        split = _greedy_split_header(blob, min_parts=4)
        if split and len(split) >= max(4, median_cols - 2):
            header = split[:median_cols] if len(split) >= median_cols else split
            actions.append("resplit_header_blob")

    # Canonical factor-table header when shape matches
    std = _maybe_standard_factor_header(header, median_cols)
    if std is not None and (
        header_looks_glued(header)
        or any(_cell_is_multi_metric(c) for c in header if c)
        or len([c for c in header if c]) < median_cols - 1
    ):
        header = list(std)
        actions.append(f"standard_factor_header→{len(header)}cols")

    target_cols = median_cols if median_cols >= 2 else len(header)
    # Prefer expanded/standard header width when close to data width
    if abs(len(header) - median_cols) <= 1 and len(header) >= 6:
        target_cols = len(header)
    elif len(header) >= median_cols and any(
        a.startswith(("expand_header", "standard_factor", "resplit")) for a in actions
    ):
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
