import re

from finreportparser.types import NumberSpan

# Regex to match numbers with optional signs, decimals, and units
# Matches: 12.3亿元, -45.6%, 100万, 50元, 12.3 YoY, 45.6同比
NUMBER_PATTERN = re.compile(
    r'(?:(?:¥|￥|RMB|CNY|USD|\$)\s*)?([+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?|\([+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?\)|（[+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?）)\s*(?:(?:-|~|至)\s*(?:(?:¥|￥|RMB|CNY|USD|\$)\s*)?(?:[+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?|\([+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?\)|（[+-]?\d+(?:[,、]\d{3})*(?:\.\d+)?）)\s*)?(亿元|万元|万|元|%\s*(?:同比|环比|YoY|QoQ)?|同比|环比|YoY|QoQ)?',
    re.IGNORECASE
)

def parse_numbers(text: str) -> list[NumberSpan]:
    spans = []
    for match in NUMBER_PATTERN.finditer(text):
        val_str = match.group(1)
        unit = match.group(2)

        is_negative = False
        if val_str.startswith('(') and val_str.endswith(')'):
            is_negative = True
            val_str = val_str[1:-1]
        elif val_str.startswith('（') and val_str.endswith('）'):
            is_negative = True
            val_str = val_str[1:-1]

        val_str = val_str.replace(',', '').replace('、', '')

        try:
            value = float(val_str)
            if is_negative:
                value = -value
        except ValueError:
            continue

        if unit:
            unit_clean = re.sub(r'\s+', '', unit)
            if 'yoy' in unit_clean.lower():
                unit = 'YoY'
            elif 'qoq' in unit_clean.lower():
                unit = 'QoQ'
            elif '同比' in unit_clean:
                unit = '同比'
            elif '环比' in unit_clean:
                unit = '环比'

        spans.append(NumberSpan(
            value=value,
            unit=unit,
            raw_text=match.group(0),
            start_idx=match.start(),
            end_idx=match.end()
        ))
    return spans

def check_table_sum_consistency(numbers: list[float], total: float, tolerance: float = 0.01) -> bool:
    return abs(sum(numbers) - total) <= tolerance
