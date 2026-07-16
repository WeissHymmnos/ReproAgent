import re

from finreportparser.fusion.rules_numbers import parse_numbers
from finreportparser.fusion.terms import canonicalize
from finreportparser.types import MetricItem

METRIC_NAMES = [
    r"营业收入", r"营收",
    r"营业成本",
    r"毛利润",
    r"净利润",
    r"归属于母公司股东的净利润", r"归属于上市公司股东的净利润", r"归属于母公司所有者的净利润", r"归母净利润",
    r"扣除非经常性损益后的净利润", r"归属于上市公司股东的扣除非经常性损益的净利润", r"扣非净利润", r"扣非",
    r"基本每股收益", r"稀释每股收益",
    r"总资产", r"归母净资产",
    r"负债合计", r"流动资产合计",
    r"经营活动现金流净额", r"投资活动现金流净额",
    r"销售毛利率", r"毛利率",
    r"净资产收益率", r"加权平均净资产收益率", r"ROE",
    r"市盈率(?:\(TTM\)|\（TTM\）)?", r"滚动市盈率", r"PE(?:_TTM)?", r"TTM"
]

METRIC_PATTERN = re.compile(
    r'(?:(?:¥|￥|RMB|CNY|USD|\$)\s*)?(?:(?:\d{4})\s*(?:年)?\s*(?:H[12]|Q[1-4])?\s*[:：]?\s*)?('
    + '|'.join(METRIC_NAMES)
    + r')\s*[:：]?\s*(同比增长|环比增长|同比下降|同比减少|同比下滑|同比\+|同比|环比|增长|上升|增加|下降|下滑|减少)?'
    r'\s*(?:(?:\d{4})\s*(?:年)?\s*(?:H[12]|Q[1-4])?\s*[:：]?\s*)?\s*(?:(?:¥|￥|RMB|CNY|USD|\$)\s*)?'
    r'([+-]?\d+(?:\.\d+)?)\s*(?:(?:-|~|至)\s*(?:(?:¥|￥|RMB|CNY|USD|\$)\s*)?[+-]?\d+(?:\.\d+)?\s*)?'
    r'(亿元|万元|万|元|%)?',
    re.IGNORECASE
)

def extract_metrics(text: str, page_num: int = None) -> list[MetricItem]:
    metrics = []
    for match in METRIC_PATTERN.finditer(text):
        raw_name = match.group(1)
        verb = match.group(2)
        val_str = match.group(3)
        unit = match.group(4)

        try:
            value = float(val_str)
        except ValueError:
            continue

        if verb and any(neg in verb for neg in ['下降', '下滑', '减少']):
            value = -abs(value)

        name = canonicalize(raw_name)

        yoy = None
        qoq = None

        lookahead_text = text[match.end():min(len(text), match.end() + 40)]
        numbers_ahead = parse_numbers(lookahead_text)
        prev_end = 0
        for num in numbers_ahead:
            context_prefix = lookahead_text[prev_end:num.start_idx]
            context_suffix = lookahead_text[num.end_idx:num.end_idx + 10]
            prev_end = num.end_idx

            is_yoy = False
            is_qoq = False

            if num.unit in ('YoY', '同比'):
                is_yoy = True
            elif num.unit in ('QoQ', '环比'):
                is_qoq = True
            else:
                if (
                    '环比' in context_prefix or 'QoQ' in context_prefix
                    or '环比' in context_suffix or 'QoQ' in context_suffix
                ):
                    is_qoq = True
                elif (
                    '同比' in context_prefix or 'YoY' in context_prefix
                    or '同比' in context_suffix or 'YoY' in context_suffix
                ):
                    is_yoy = True
                elif (
                    context_prefix.strip().endswith(('(', '（'))
                    and context_suffix.strip().startswith((')', '）'))
                    and num.unit == '%'
                ):
                    is_yoy = True
                elif any(v in context_prefix for v in ['增长', '上升', '增加', '下降', '下滑', '减少']):
                    is_yoy = True

            if is_yoy:
                val = num.value
                if any(neg in context_prefix for neg in ['下降', '下滑', '减少']):
                    val = -abs(val)
                yoy = val
            elif is_qoq:
                val = num.value
                if any(neg in context_prefix for neg in ['下降', '下滑', '减少']):
                    val = -abs(val)
                qoq = val

        metrics.append(MetricItem(
            name=name,
            raw_name=raw_name,
            value=value,
            unit=unit,
            raw_value=match.group(0),
            yoy=yoy,
            qoq=qoq,
            page_num=page_num
        ))
    return metrics

def extract_metrics_from_table(markdown: str, page_num: int = None) -> list[MetricItem]:
    metrics = []
    lines = markdown.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line.startswith('|') or not line.endswith('|'):
            continue
        # Skip separator rows
        if re.match(r'^\|(?:\s*-+\s*\|)+$', line):
            continue

        cells = [c.strip() for c in line.strip('|').split('|')]
        if not cells:
            continue

        first_cell = cells[0]
        if not first_cell:
            continue

        # Check if first cell is a known metric
        name = canonicalize(first_cell)
        is_known = False
        if name != first_cell:
            is_known = True
        else:
            for pattern in METRIC_NAMES:
                if re.fullmatch(pattern, first_cell, re.IGNORECASE):
                    is_known = True
                    break

        if not is_known:
            continue

        for cell in cells[1:]:
            if not cell:
                continue
            synthetic_text = f"{first_cell} {cell}"
            cell_metrics = extract_metrics(synthetic_text, page_num=page_num)
            if cell_metrics:
                metrics.extend(cell_metrics)
            else:
                # Fallback to parse_numbers
                nums = parse_numbers(cell)
                if nums:
                    num = nums[0]
                    metrics.append(MetricItem(
                        name=name,
                        raw_name=first_cell,
                        value=num.value,
                        unit=num.unit,
                        raw_value=cell,
                        yoy=None,
                        qoq=None,
                        page_num=page_num
                    ))

    return metrics

def metrics_to_markdown_table(metrics: list[MetricItem]) -> str:
    if not metrics:
        return ""

    lines = [
        "| Metric | Value | Unit | YoY | QoQ | Page |",
        "|---|---|---|---|---|---|"
    ]

    for m in metrics:
        val_str = str(m.value) if m.value is not None else "-"
        unit_str = m.unit if m.unit else "-"
        yoy_str = f"{m.yoy}%" if m.yoy is not None else "-"
        qoq_str = f"{m.qoq}%" if m.qoq is not None else "-"
        page_str = str(m.page_num) if m.page_num is not None else "-"

        lines.append(f"| {m.name} | {val_str} | {unit_str} | {yoy_str} | {qoq_str} | {page_str} |")

    return "\n".join(lines)
