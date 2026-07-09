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
        raise NotImplementedError("SchemaValidator.validate")

    def validate_all(self, specs: list[ParsedFactorSpec]) -> list[ParsedFactorSpec]:
        """批量校验。"""
        return [self.validate(s) for s in specs]
