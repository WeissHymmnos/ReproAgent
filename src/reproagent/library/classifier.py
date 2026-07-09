"""风格自动分类：规则优先 + LLM fallback。"""

from __future__ import annotations

from reproagent.models.factor_def import FactorDefinition


class StyleClassifier:
    """规则优先 + LLM fallback。"""

    RULES: dict[str, list[str]] = {
        "momentum": ["动量", "momentum", "ret", "return", "涨跌"],
        "value": ["估值", "value", "PE", "PB", "市盈率", "市净率"],
        "quality": ["质量", "quality", "ROE", "ROA", "盈利"],
        "volatility": ["波动", "volatility", "vol", "std"],
        "liquidity": ["流动性", "liquidity", "turnover", "换手", "成交"],
        "size": ["市值", "size", "cap", "规模"],
        "growth": ["成长", "growth", "增长", "YoY"],
    }

    def classify(self, factor: FactorDefinition) -> str:
        """返回 style 字符串（与 FactorDefinition.style 对齐）。"""
        raise NotImplementedError("StyleClassifier.classify")

    def _llm_classify(self, factor: FactorDefinition) -> str:
        raise NotImplementedError("StyleClassifier._llm_classify")
