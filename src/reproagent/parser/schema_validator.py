"""Schema 校验 + 数据字典映射 [OK]/[WARN]。"""

from __future__ import annotations

from typing import Any, Literal

from reproagent.models.factor_spec import DataDictMapping, ParsedFactorSpec


class SchemaValidator:
    """校验公式、数据字典映射与提取置信度。"""

    def validate(self, spec: ParsedFactorSpec) -> ParsedFactorSpec:
        """校验并标注 [OK]/[WARN]。

        1. 公式语法校验
        2. 数据字典映射（高置信 OK / 低置信 WARN）
        3. extraction_confidence 阈值
        """
        if not spec.factor_name:
            raise ValueError("factor_name cannot be empty")
        if not spec.formula:
            raise ValueError("formula cannot be empty")

        description = spec.description

        # 1. 简单的公式语法校验 (检查括号匹配)
        open_brackets = {"(": ")", "[": "]", "{": "}"}
        stack: list[str] = []
        for char in spec.formula:
            if char in open_brackets:
                stack.append(char)
            elif char in open_brackets.values():
                if not stack or open_brackets[stack.pop()] != char:
                    description += "\n[WARN] Formula has mismatched brackets."
                    break
        if stack:
            description += "\n[WARN] Formula has unclosed brackets."

        # 2. 数据字典映射（股票 + 转债）
        canonical_map = {
            "收盘价": "close",
            "开盘价": "open",
            "最高价": "high",
            "最低价": "low",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover_rate",
            "市盈率": "pe_ttm",
            "市净率": "pb",
            "收益率": "returns",
            # 转债
            "到期收益率": "ytm",
            "YTM": "ytm",
            "ytm": "ytm",
            "债性": "ytm",
            "平价溢价率": "premium_rate",
            "转股溢价率": "premium_rate",
            "溢价率": "premium_rate",
            "债底": "bond_value",
            "纯债价值": "bond_value",
            "隐含波动率": "implied_vol",
            "隐波": "implied_vol",
            "期权价值": "option_value",
            "剩余规模": "remaining_size",
            "转股价": "conversion_price",
            "绝对价格": "close",
            "转债价格": "close",
        }

        new_mappings: list[DataDictMapping] = []
        for mapping in spec.data_dict_mappings:
            tag: Literal["OK", "WARN"] = "OK" if mapping.confidence >= 0.8 else "WARN"
            new_mappings.append(mapping.model_copy(update={"tag": tag}))

        # 如果 LLM 没有提供 mappings，我们尝试基于 input_fields 自动映射
        if not new_mappings and spec.input_fields:
            for field in spec.input_fields:
                canonical = canonical_map.get(field.report_name, field.name)
                confidence = 1.0 if field.report_name in canonical_map else 0.5
                tag = "OK" if confidence >= 0.8 else "WARN"
                new_mappings.append(
                    DataDictMapping(
                        report_term=field.report_name,
                        canonical_term=canonical,
                        confidence=confidence,
                        tag=tag,
                        note=("Auto-mapped" if confidence >= 0.8 else "Fallback mapping"),
                    )
                )

        update_dict: dict[str, Any] = {"data_dict_mappings": new_mappings}

        # 3. extraction_confidence 阈值
        if spec.extraction_confidence < 0.5:
            description += "\n[WARN] Low extraction confidence."

        update_dict["description"] = description
        return spec.model_copy(update=update_dict)

    def validate_all(self, specs: list[ParsedFactorSpec]) -> list[ParsedFactorSpec]:
        """批量校验。"""
        return [self.validate(s) for s in specs]
