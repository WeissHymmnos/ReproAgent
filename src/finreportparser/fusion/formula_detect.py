import re
from dataclasses import dataclass


@dataclass
class FormulaSpan:
    start_idx: int
    end_idx: int
    lines: list[str]

def is_formula_line(line: str) -> bool:
    if not line.strip():
        return False

    # Hard rejects
    if re.search(r'\[Table_[A-Za-z0-9_]+\]', line):
        return False
    if re.search(r'Tel:|Email:|证书:', line, re.IGNORECASE):
        return False

    pua_count = sum(1 for c in line if '\uE000' <= c <= '\uF8FF')
    pua_density = pua_count / len(line) if len(line) > 0 else 0
    cjk_count = len(re.findall(r'[\u4e00-\u9fff]', line))

    if cjk_count > 40 and pua_density < 0.02 and not re.search(r'ES|VaR|∑|\\sum|[≤≥=+\-]', line):
        return False

    score = 0

    # 1. PUA density
    if pua_count > 0:
        score += pua_count * 3

    # 2. Contains ES/VaR/CVaR with operators (including PUA as operators)
    if re.search(r'(ES|VaR|CVaR)', line):
        if re.search(r'[=+\-*/<>\(\)\[\]]', line) or pua_count > 0:
            score += 5

    # 3. Trailing equation number pattern
    if re.search(r'。\s*\(\d+\)$', line) or re.search(r'\(\d+\)\s*$', line):
        score += 5

    # 4. Short lines heavy in operators + Latin math letters
    operators_count = len(re.findall(r'[=+\-*/<>\(\)\[\]]', line))
    latin_count = len(re.findall(r'[a-zA-Z]', line))
    if len(line) < 50 and (operators_count > 0 or pua_count > 0) and latin_count > 0:
        score += min(5, operators_count + pua_count)

    # 5. Reject long pure Chinese prose paragraphs without operators/PUA
    if len(line) > 30 and cjk_count > len(line) * 0.5 and operators_count == 0 and pua_count == 0:
        score -= 10

    return score >= 5

def find_formula_lines(text: str) -> list[FormulaSpan]:
    lines = text.split('\n')
    spans = []

    in_formula = False
    start_idx = -1
    formula_lines = []

    for i, line in enumerate(lines):
        if is_formula_line(line):
            if not in_formula:
                in_formula = True
                start_idx = i
            formula_lines.append(line)
        else:
            if in_formula:
                spans.append(FormulaSpan(start_idx, i - 1, formula_lines))
                in_formula = False
                formula_lines = []

    if in_formula:
        spans.append(FormulaSpan(start_idx, len(lines) - 1, formula_lines))

    return spans
