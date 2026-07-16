import re

# Mapping from PUA characters to Unicode equivalents
PUA_TO_UNICODE = {
    "\uf0e5": "∑",
    "\uf0a3": "≤",
    "\uf03d": "=",
    "\uf02b": "+",
    "\uf02d": "-",
    "\uf0e6": "",  # Top left paren
    "\uf0e7": "(", # Middle left paren
    "\uf0e8": "",  # Bottom left paren
    "\uf0f6": "",  # Top right paren
    "\uf0f7": ")", # Middle right paren
    "\uf0f8": "",  # Bottom right paren
    "\uf028": "(",
    "\uf029": ")",
    "\uf05b": "[",
    "\uf05d": "]",
    "\uf065": "ε",
    "\uf0b9": "≠",
    "\uf04c": "…", # 
    "\uf04d": "…", # 
    "\uf04b": "…", # 
    "\uf04f": "…", # 
}

# Mapping from PUA characters to LaTeX equivalents
PUA_TO_LATEX = {
    "\uf0e5": "\\sum",
    "\uf0a3": "\\leq",
    "\uf03d": "=",
    "\uf02b": "+",
    "\uf02d": "-",
    "\uf0e6": "",
    "\uf0e7": "(",
    "\uf0e8": "",
    "\uf0f6": "",
    "\uf0f7": ")",
    "\uf0f8": "",
    "\uf028": "(",
    "\uf029": ")",
    "\uf05b": "[",
    "\uf05d": "]",
    "\uf065": "\\varepsilon",
    "\uf0b9": "\\neq",
    "\uf04c": "\\dots",
    "\uf04d": "\\dots",
    "\uf04b": "\\dots",
    "\uf04f": "\\dots",
}

def is_bullet_context(s: str) -> bool:
    """
    Determine if a lambda () is used as a bullet point.
    Heuristic: It's a bullet if it's at the start of the string (ignoring whitespace)
    and followed by Chinese characters or typical prose.
    """
    s = s.strip()
    if not s.startswith("\uf06c"):
        return False

    # Check if there are Chinese characters nearby
    # Chinese character range: \u4e00-\u9fff
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', s))
    return has_chinese

def normalize_formula_text(s: str) -> str:
    """
    Convert PUA characters to standard Unicode.
    """
    if not s:
        return s

    # Handle lambda/bullet context
    if "\uf06c" in s:
        if is_bullet_context(s):
            s = s.replace("\uf06c", "•")
        else:
            s = s.replace("\uf06c", "λ")

    # Replace other PUA characters
    res = []
    for char in s:
        if char in PUA_TO_UNICODE:
            res.append(PUA_TO_UNICODE[char])
        else:
            res.append(char)

    return "".join(res)

def to_latex_approx(s: str) -> str:
    """
    Convert PUA characters to approximate LaTeX.
    """
    if not s:
        return s

    # Handle lambda/bullet context
    if "\uf06c" in s:
        if is_bullet_context(s):
            s = s.replace("\uf06c", "•")
        else:
            s = s.replace("\uf06c", "\\lambda")

    # Replace other PUA characters
    res = []
    for char in s:
        if char in PUA_TO_LATEX:
            res.append(PUA_TO_LATEX[char])
        else:
            res.append(char)

    # Basic cleanup for LaTeX
    latex_str = "".join(res)

    latex_str = re.sub(r'\bESi\b', 'ES_i', latex_str)
    latex_str = re.sub(r'\bXi\b', 'X_i', latex_str)
    latex_str = re.sub(r'\bwi\b', 'w_i', latex_str)

    # Add spaces around operators for better readability if they don't have them
    # This is a very basic heuristic
    latex_str = re.sub(r'(?<!\s)(\\leq|\\sum|\\lambda|\\dots)(?!\s)', r' \1 ', latex_str)
    latex_str = re.sub(r'\s+', ' ', latex_str).strip()

    return latex_str

def map_line(s: str) -> tuple[str, str]:
    """
    Return both Unicode and LaTeX approximations for a line.
    """
    return normalize_formula_text(s), to_latex_approx(s)

def is_trivial_formula_latex(latex: str) -> bool:
    if not latex or not latex.strip():
        return True
    stripped = re.sub(r"\s+", "", latex)
    if stripped in {"(", ")", "((", "))", "...", "…", "\\dots"}:
        return True
    if len(stripped) < 4 and not re.search(r"ES|\\sum|∑|\\leq|≤|\\lambda|w_", latex):
        return True
    return False

def is_usable_latex(latex: str) -> bool:
    if not latex or not latex.strip():
        return False
    if len(latex) > 350:
        return False
    if latex.count("\\stackrel") >= 3:
        return False
    if latex.count("\\pi") >= 4 and "ES" not in latex and "VaR" not in latex:
        return False
    stripped = latex.strip()
    if re.fullmatch(r"\\mathbf\{.?\}", stripped):
        return False
    if re.fullmatch(r"\\frac\{1\}\s*\{\s*2\s*\}", stripped):
        return False
    if stripped in {"((", "))", "(", ")"}:
        return False
    if len(re.findall(r"\{\s*\}", latex)) > 6:
        return False
    if re.fullmatch(r"\s*\(\s*\d+\s*\)\s*", latex):
        return False
    if "\\begin{array}" in latex and not re.search(r"ES|\\sum|w_|\\leq|\\lambda|VaR|X_", latex):
        return False
    return True

def worth_l3_recognition(formula_text: str, eq_number: str | None) -> bool:
    if eq_number is not None:
        return True
    if re.search(r"\bES\b|\bVaR\b|\bCVaR\b", formula_text):
        return True
    if formula_text and sum(1 for c in formula_text if 0xE000 <= ord(c) <= 0xF8FF) / max(len(formula_text), 1) > 0.02:
        return True
    return False
