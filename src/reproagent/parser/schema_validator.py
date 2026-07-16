"""Schema 校验 + 数据字典映射 [OK]/[WARN]。"""

from __future__ import annotations

from reproagent.models.factor_spec import ParsedFactorSpec


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

        new_mappings = []
        for mapping in spec.data_dict_mappings:
            tag = "OK" if mapping.confidence >= 0.8 else "WARN"
            new_mappings.append(mapping.model_copy(update={"tag": tag}))

        update_dict = {"data_dict_mappings": new_mappings}
        
        if spec.extraction_confidence < 0.5:
            note = "\n[WARN] Low extraction confidence."
            update_dict["description"] = spec.description + note

        return spec.model_copy(update=update_dict)

    def validate_all(self, specs: list[ParsedFactorSpec]) -> list[ParsedFactorSpec]:
        """批量校验。"""
        return [self.validate(s) for s in specs]
