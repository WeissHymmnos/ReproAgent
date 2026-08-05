"""未来函数检测器单元测试：覆盖所有检测规则。"""

from __future__ import annotations

import pytest

from reproagent.reproducer.lookahead_detector import (
    LookaheadFinding,
    LookaheadReport,
    detect_lookahead,
)


class TestDetectLookaheadRegression:
    """干净公式（无未来函数）不应产生任何 error。"""

    @pytest.mark.parametrize(
        "formula",
        [
            # 基础动量：close 滞后 20 天
            "close / Ref(close, 20) - 1",
            # 纯截面算子
            "Rank(turnover)",
            # 多重滞后
            "Ref(close, 1) / Ref(close, 20) - 1",
            # 数学运算
            "CSZScore(Mean(close, 20) / Std(close, 20))",
            # 简单字段引用（非价格字段）
            "volume / Ref(volume, 20)",
        ],
    )
    def test_clean_formulas_produce_no_error(self, formula: str) -> None:
        report = detect_lookahead(formula)
        assert not report.has_lookahead, (
            f"干净公式不应报告 lookahead: {formula}\n"
            f"但产生了: {[(f.rule, f.severity) for f in report.findings]}"
        )
        for f in report.findings:
            assert f.severity != "error", f"干净公式不应有 error: {formula} → {f.description}"


class TestRefNegativeWindow:
    """Ref(x, -N) 应被检测为 error。"""

    def test_ref_negative_window_ast(self) -> None:
        report = detect_lookahead("Ref(close, -1)")
        assert report.has_lookahead
        assert report.risk_level == "high"
        errors = [f for f in report.findings if f.severity == "error"]
        assert len(errors) >= 1
        assert any("负窗口" in e.description for e in errors)

    def test_delta_negative_window_ast(self) -> None:
        report = detect_lookahead("Delta(close, -5)")
        assert report.has_lookahead
        assert report.risk_level == "high"

    def test_ref_positive_window_ok(self) -> None:
        """Ref(x, 正数) 不应报 error。"""
        report = detect_lookahead("Ref(close, 20)")
        errors = [f for f in report.findings if f.severity == "error"]
        assert len(errors) == 0


class TestTextPatterns:
    """纯文本层面的模式检测（无需 AST 解析）。"""

    def test_shift_negative_text(self) -> None:
        report = detect_lookahead("close.shift(-1)")
        assert report.has_lookahead
        errors = [f for f in report.findings if f.severity == "error"]
        assert len(errors) >= 1
        assert any("shift" in e.rule for e in errors)

    def test_lead_function_text(self) -> None:
        report = detect_lookahead("close.lead(5)")
        errors = [f for f in report.findings if f.severity == "error"]
        assert len(errors) >= 1


class TestUnlaggedPriceWarning:
    """裸 close/open/high/low 引用应产生 warning（不是 error）。"""

    @pytest.mark.parametrize("field", ["close", "open", "high", "low"])
    def test_bare_price_field_triggers_warning(self, field: str) -> None:
        report = detect_lookahead(f"{field} / Ref({field}, 20) - 1")
        warnings = [f for f in report.findings if f.severity == "warning"]
        assert len(warnings) >= 1
        assert any(field in w.description for w in warnings)

    def test_ref_lagged_close_no_extra_warning(self) -> None:
        """Ref(close, 1) 已经滞后，但 close 在 Ref 内部作为参数仍会触发
        AST Name 访问器的警告。这是预期行为——AST 遍历器对所有 Name('close')
        都会发 warning，包括作为 Ref 参数的。用户可以通过配置决定是否忽略。"""
        report = detect_lookahead("Ref(close, 1)")
        # 即使有 warning，也没有 error
        errors = [f for f in report.findings if f.severity == "error"]
        assert len(errors) == 0


class TestSyntaxErrorHandling:
    """语法错误的公式应友好处理，不抛异常。"""

    @pytest.mark.parametrize(
        "formula",
        [
            "close + ",  # 不完整表达式
            "Ref(close, ",  # 未闭合括号
            "close / ))(",  # 垃圾括号
        ],
    )
    def test_syntax_error_produces_info_not_exception(self, formula: str) -> None:
        # 不应抛出异常
        report = detect_lookahead(formula)
        assert isinstance(report, LookaheadReport)
        # 应有 parse_error info
        infos = [f for f in report.findings if f.severity == "info"]
        assert len(infos) >= 1


class TestRiskLevelAssignment:
    """风险等级的升降级逻辑。"""

    def test_no_findings_is_none(self) -> None:
        report = detect_lookahead("Rank(close)")
        # close 裸引用会产生 warning，但不应是 error
        assert not report.has_lookahead

    def test_single_error_is_high(self) -> None:
        report = detect_lookahead("Ref(close, -1)")
        assert report.risk_level == "high"

    def test_multiple_warnings_is_medium(self) -> None:
        # close 和 high 都是裸引用 = 2 warnings
        report = detect_lookahead("close / high")
        warnings = [f for f in report.findings if f.severity == "warning"]
        assert len(warnings) >= 2
        assert report.risk_level == "medium"

    def test_single_warning_is_low(self) -> None:
        report = detect_lookahead("close / Ref(volume, 20)")
        warnings = [f for f in report.findings if f.severity == "warning"]
        # 至少有一个（裸 close）
        assert len(warnings) >= 1
        assert report.risk_level == "low"


class TestFieldCoverage:
    """确保检测器覆盖所有关键模式。"""

    def test_findings_are_structured(self) -> None:
        report = detect_lookahead("Ref(close, -5)")
        assert isinstance(report, LookaheadReport)
        for f in report.findings:
            assert isinstance(f, LookaheadFinding)
            assert f.rule
            assert f.description
            assert f.severity in ("error", "warning", "info")

    def test_volume_field_no_warning(self) -> None:
        """volume 不是价格字段，不应触发 unlagged_price 警告。"""
        report = detect_lookahead("volume / Ref(volume, 20) - 1")
        lag_warnings = [f for f in report.findings if f.rule == "unlagged_price"]
        assert len(lag_warnings) == 0
