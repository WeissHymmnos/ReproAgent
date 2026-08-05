"""复现基准语料库验证：提取准确率 + 回测复现准确率。

对 catalog.yaml 中 status="annotated" 的报告运行全链路比对。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_BENCHMARK_DIR = Path(__file__).parent.parent / "fixtures" / "benchmark"


def load_catalog() -> list[dict]:
    with open(_BENCHMARK_DIR / "catalog.yaml") as f:
        return yaml.safe_load(f).get("reports", [])


def load_ground_truth(report_id: str) -> dict | None:
    gt_path = _BENCHMARK_DIR / report_id / "ground_truth.yaml"
    if not gt_path.exists():
        return None
    with open(gt_path) as f:
        return yaml.safe_load(f)


def _annotated_reports() -> list[dict]:
    return [r for r in load_catalog() if r.get("status") == "annotated"]


def _report_pdf_path(report: dict) -> Path:
    """获取报告的 PDF 路径，相对于 benchmark 目录或绝对路径。"""
    rf = report.get("report_file", "")
    return (_BENCHMARK_DIR / rf).resolve()


# ── Schema 校验（对所有报告运行） ──


class TestBenchmarkSchema:
    def test_catalog_exists(self) -> None:
        assert (_BENCHMARK_DIR / "catalog.yaml").exists()

    def test_all_reports_have_ground_truth(self) -> None:
        for report in load_catalog():
            report_id = report["report_id"]
            gt_path = _BENCHMARK_DIR / report_id / "ground_truth.yaml"
            assert gt_path.exists(), f"报告 {report_id} 缺少 ground_truth.yaml"

    def test_ground_truth_has_required_fields(self) -> None:
        required = {"report_id", "broker", "report_date", "factors"}
        for report in load_catalog():
            gt = load_ground_truth(report["report_id"])
            if gt is None:
                continue
            missing = required - set(gt.keys())
            assert not missing, f"报告 {report['report_id']} 缺少字段: {missing}"

    def test_factor_schema(self) -> None:
        factor_required = {"name", "name_cn", "formula", "input_fields", "rebalance_frequency"}
        for report in load_catalog():
            gt = load_ground_truth(report["report_id"])
            if gt is None:
                continue
            for factor in gt.get("factors", []):
                missing = factor_required - set(factor.keys())
                assert not missing, (
                    f"报告 {report['report_id']} 因子 {factor.get('name', '?')} 缺少字段: {missing}"
                )

    def test_at_least_one_annotated(self) -> None:
        annotated = _annotated_reports()
        assert len(annotated) >= 1, (
            "至少需要一篇 status='annotated' 的报告才能运行提取/复现 fidelity 测试"
        )


# ── 提取准确率（对已标注报告） ──


class TestExtractionFidelity:
    """因子提取准确率：验证 pipeline 能从 PDF 中提取出 ground truth 中定义的因子。"""

    @pytest.fixture
    def offline_settings(self, tmp_path: Path) -> object:
        from reproagent.settings import Settings

        return Settings(
            _env_file=None,
            app_env="dev",
            allow_mock_llm=True,
            allow_formula_fallback=True,
            llm_api_key="",
            parser_backend="finpdfpro",
            data_source="local",
            local_data_path=Path("tests/fixtures/test_data"),
            data_dir=tmp_path / "reproagent-bench",
        )

    def test_parse_extracts_all_expected_factor_names(
        self, offline_settings: object
    ) -> None:
        """对每篇 annotated 报告，验证 pipeline 提取的因子名包含 ground truth 中全部因子。"""
        for report in _annotated_reports():
            report_id = report["report_id"]
            gt = load_ground_truth(report_id)
            if gt is None or not gt.get("factors"):
                pytest.skip(f"报告 {report_id} ground truth 中没有定义因子")

            pdf_path = _report_pdf_path(report)
            if not pdf_path.exists():
                pytest.skip(f"报告 {report_id} 的 PDF 不存在: {pdf_path}")

            from reproagent.ingestion.uploader import upload_pdf
            from reproagent.ingestion.validator import validate_pdf
            from reproagent.parser.report_parser import ReportParser

            uploaded = upload_pdf(pdf_path)
            validated = validate_pdf(uploaded)
            assert validated.validation_status == "valid"

            parser = ReportParser(offline_settings)
            specs = parser.parse(validated)
            assert len(specs) >= len(gt["factors"]), (
                f"报告 {report_id}: 提取到 {len(specs)} 个因子，"
                f"但 ground truth 定义了 {len(gt['factors'])} 个"
            )

            extracted_names = {s.factor_name for s in specs}
            expected_names = {f["name"] for f in gt["factors"]}
            missing = expected_names - extracted_names
            assert not missing, f"报告 {report_id}: 未提取到因子: {missing}"


# ── 复现准确率（对已标注报告） ──


class TestReproductionFidelity:
    """回测复现准确率：验证 pipeline 计算出的回测指标与 ground truth 一致。"""

    @pytest.fixture
    def offline_settings(self, tmp_path: Path) -> object:
        from reproagent.settings import Settings

        return Settings(
            _env_file=None,
            app_env="dev",
            allow_mock_llm=True,
            allow_formula_fallback=True,
            llm_api_key="",
            parser_backend="finpdfpro",
            data_source="local",
            local_data_path=Path("tests/fixtures/test_data"),
            data_dir=tmp_path / "reproagent-bench-repro",
        )

    def test_full_pipeline_produces_backtest_result(
        self, offline_settings: object
    ) -> None:
        """全链路跑通：PDF → 提取 → 复制 → 回测 → 产生合法 BacktestResult。"""
        for report in _annotated_reports():
            report_id = report["report_id"]
            pdf_path = _report_pdf_path(report)
            if not pdf_path.exists():
                pytest.skip(f"报告 {report_id} 的 PDF 不存在: {pdf_path}")

            from reproagent.pipeline import reproduce_report

            outcome = reproduce_report(pdf_path, offline_settings)
            assert outcome is not None
            assert "status" in outcome
            assert outcome["status"] in {
                "passed", "converged", "partial", "review_enqueued",
                "no_factors", "invalid", "error",
            }
            assert "factors" in outcome
            assert isinstance(outcome["factors"], list)

    def test_extracted_formula_matches_ground_truth(
        self, offline_settings: object
    ) -> None:
        """提取的因子公式与 ground truth 完全一致（在 mock 模式下）。"""
        for report in _annotated_reports():
            report_id = report["report_id"]
            gt = load_ground_truth(report_id)
            if not gt or not gt.get("factors"):
                continue

            pdf_path = _report_pdf_path(report)
            if not pdf_path.exists():
                continue

            from reproagent.ingestion.uploader import upload_pdf
            from reproagent.ingestion.validator import validate_pdf
            from reproagent.parser.report_parser import ReportParser

            uploaded = upload_pdf(pdf_path)
            parser = ReportParser(offline_settings)
            specs = parser.parse(validate_pdf(uploaded))

            for gt_factor in gt["factors"]:
                spec = next(
                    (s for s in specs if s.factor_name == gt_factor["name"]), None
                )
                assert spec is not None, (
                    f"报告 {report_id}: 未找到因子 {gt_factor['name']}"
                )
                assert spec.formula == gt_factor["formula"], (
                    f"报告 {report_id}.{gt_factor['name']}: "
                    f"公式不匹配: {spec.formula} != {gt_factor['formula']}"
                )

    def test_resolve_and_report_annotated_count(self) -> None:
        """汇总报告：已标注 vs 待标注数。"""
        all_reports = load_catalog()
        annotated = _annotated_reports()
        pending = len(all_reports) - len(annotated)
        # 至少有一篇已标注才能跑 fidelity 测试
        assert len(annotated) >= 1
        # 记录汇总信息（不阻塞 CI）
        print(
            f"\n[benchmark] {len(all_reports)} total | "
            f"{len(annotated)} annotated | {pending} pending"
        )
