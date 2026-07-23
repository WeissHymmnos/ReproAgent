"""风格自动分类：规则优先 + LLM fallback。"""

from __future__ import annotations

from reproagent.models.factor_def import FactorDefinition

_VALID_STYLES = frozenset(
    {
        "value",
        "growth",
        "momentum",
        "quality",
        "size",
        "volatility",
        "liquidity",
        "macro",
        "technical",
        "other",
    }
)


class StyleClassifier:
    """规则优先 + LLM fallback。

    若因子已有明确非 other 风格，默认保留，避免入库时被规则误覆盖。
    """

    RULES: dict[str, list[str]] = {
        "momentum": ["动量", "momentum", "ret", "return", "涨跌"],
        "value": ["估值", "value", "PE", "PB", "市盈率", "市净率"],
        "quality": ["质量", "quality", "ROE", "ROA", "盈利"],
        "volatility": ["波动", "volatility", "vol", "std"],
        "liquidity": ["流动性", "liquidity", "turnover", "换手", "成交"],
        "size": ["市值", "size", "cap", "规模"],
        "growth": ["成长", "growth", "增长", "YoY"],
    }

    def classify(self, factor: FactorDefinition, *, force: bool = False) -> str:
        """返回 style 字符串（与 FactorDefinition.style 对齐）。

        force=True 时忽略已有 style，强制重分类。
        """
        if (
            not force
            and factor.style
            and factor.style != "other"
            and factor.style in _VALID_STYLES
        ):
            return factor.style

        text = (factor.name + " " + factor.name_cn + " " + factor.formula).lower()
        for style, keywords in self.RULES.items():
            for kw in keywords:
                if kw.lower() in text:
                    return style
        matched = self._llm_classify(factor)
        if matched != "other":
            return matched
        return "other"

    def _llm_classify(self, factor: FactorDefinition) -> str:
        """无 API key 时退化为规则扩展匹配（mock）。"""
        text = (factor.name + " " + factor.name_cn + " " + factor.formula).lower()
        extended = {
            "technical": ["ma", "macd", "rsi", "boll", "kdj", "技术", "technical"],
            "macro": ["gdp", "cpi", "pmi", "宏观", "macro"],
        }
        for style, keywords in extended.items():
            for kw in keywords:
                if kw.lower() in text:
                    return style
        return "other"
