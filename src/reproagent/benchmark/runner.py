"""Benchmark 全链路 runner：ground_truth → 计算 → 偏差比对。

不依赖 LLM 提取：直接用标注公式构建 ParsedFactorSpec，保证可回归。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from reproagent.models.deviation import ToleranceConfig
from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ReportedMetrics
from reproagent.settings import Settings

_DEFAULT_BENCHMARK_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "benchmark"
)


def _benchmark_dir() -> Path:
    return _DEFAULT_BENCHMARK_DIR


def load_catalog(benchmark_dir: Path | None = None) -> list[dict[str, Any]]:
    root = benchmark_dir or _benchmark_dir()
    catalog_path = root / "catalog.yaml"
    with open(catalog_path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("reports", [])


def load_ground_truth(report_id: str, benchmark_dir: Path | None = None) -> dict[str, Any]:
    root = benchmark_dir or _benchmark_dir()
    gt_path = root / report_id / "ground_truth.yaml"
    if not gt_path.exists():
        raise FileNotFoundError(f"ground_truth not found: {gt_path}")
    with open(gt_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid ground_truth: {gt_path}")
    return data


def _parse_date(value: Any, default: date) -> date:
    if value is None:
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _spec_from_gt_factor(factor: dict[str, Any]) -> ParsedFactorSpec:
    """将 ground_truth 中的因子条目转为 ParsedFactorSpec。"""
    input_fields_raw = factor.get("input_fields") or ["close"]
    input_fields: list[FactorInputField] = []
    for name in input_fields_raw:
        input_fields.append(
            FactorInputField(
                name=str(name),
                report_name=str(name),
                data_type=(
                    "price"
                    if name in {"open", "high", "low", "close", "volume", "amount"}
                    else "fundamental"
                ),
            )
        )

    reported = None
    rm = factor.get("reported_metrics")
    if isinstance(rm, dict):
        claimed: dict[str, Any] = {}
        for key in (
            "ic_mean",
            "ic_ir",
            "long_short_return",
            "sharpe_ratio",
            "max_drawdown",
        ):
            if key not in rm:
                continue
            value = rm[key]
            if value is None:
                continue
            claimed[key] = value
        if claimed:
            reported = ReportedMetrics(**claimed)

    rebalance = factor.get("rebalance_frequency", "monthly")
    if rebalance not in ("daily", "weekly", "monthly", "quarterly"):
        rebalance = "monthly"

    return ParsedFactorSpec(
        id=uuid.uuid4().hex,
        factor_name=str(factor["name"]),
        factor_name_cn=str(factor.get("name_cn") or factor["name"]),
        description=str(factor.get("annotation_notes") or factor.get("description") or ""),
        formula=str(factor["formula"]),
        input_fields=input_fields,
        computation_steps=list(factor.get("computation_steps") or []),
        rebalance_frequency=rebalance,  # type: ignore[arg-type]
        universe=str(factor.get("universe") or "全A股"),
        lookback_window=factor.get("lookback_window"),
        extraction_confidence=1.0,
        reported_metrics=reported,
    )


def _default_backtest_window(gt: dict[str, Any]) -> tuple[date, date]:
    """从 ground_truth 或合理默认取回测窗口（对齐本地 fixture）。"""
    params = gt.get("backtest_params") or {}
    start = _parse_date(params.get("start_date"), date(2023, 1, 2))
    end = _parse_date(params.get("end_date"), date(2023, 2, 10))
    return start, end


def run_benchmark(
    report_id: str,
    settings: Settings | None = None,
    *,
    benchmark_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """对单篇 report_id 运行 ground_truth 驱动的全链路比对。

    Returns
    -------
    dict: report_id, status, factors[], summary
    """
    from reproagent.deviation.analyzer import DeviationAnalyzer
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.reproducer.data_loader import DataLoader
    from reproagent.reproducer.reproducer import FactorReproducer

    settings = settings or Settings()
    root = benchmark_dir or _benchmark_dir()
    gt = load_ground_truth(report_id, root)
    factors_gt: list[dict[str, Any]] = list(gt.get("factors") or [])

    if not factors_gt:
        return {
            "report_id": report_id,
            "status": "no_factors",
            "factors": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0},
            "message": "ground_truth has no factors to benchmark",
        }

    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    engine = get_engine(settings.db_path)
    init_db(engine)
    _ = Repository(engine)  # ensure schema side-effects for shared data_dir

    data_loader = DataLoader(settings)
    reproducer = FactorReproducer(settings, data_loader)
    analyzer = DeviationAnalyzer()
    tolerances = ToleranceConfig()

    start, end = _default_backtest_window(gt)
    factor_results: list[dict[str, Any]] = []
    n_passed = n_failed = n_errors = 0

    for factor in factors_gt:
        name = str(factor.get("name", "?"))
        try:
            spec = _spec_from_gt_factor(factor)
            config = ReplicationConfig(
                id=uuid.uuid4().hex,
                report_id=gt.get("report_id") or report_id,
                factor_specs=[spec],
                engine=settings.default_engine,
                data_source=settings.data_source,  # type: ignore[arg-type]
                backtest_params=BacktestParams(
                    start_date=start,
                    end_date=end,
                    rebalance_frequency=spec.rebalance_frequency,
                ),
                parser_version=settings.parser_version,
                extraction_model_id="benchmark-ground-truth",
                created_at=datetime.now(UTC),
            )
            bt = reproducer.reproduce(config)
            reported = spec.reported_metrics or ReportedMetrics()
            deviation = analyzer.analyze(bt, reported, tolerances)

            # 计算是否产出有效因子值
            values_ok = False
            try:
                import polars as pl

                if bt.factor_values_path.exists():
                    fv = pl.read_parquet(bt.factor_values_path)
                    if "factor_value" in fv.columns and fv["factor_value"].drop_nulls().len() > 0:
                        values_ok = True
            except Exception:  # noqa: BLE001
                values_ok = False

            # 有 reported_metrics 时以偏差门控为准；否则以可计算为准
            has_targets = any(
                getattr(reported, k) is not None
                for k in ("ic_mean", "ic_ir", "long_short_return", "sharpe_ratio", "max_drawdown")
            )
            passed = bool(deviation.passed) if has_targets else values_ok
            if passed:
                n_passed += 1
            else:
                n_failed += 1

            factor_results.append(
                {
                    "name": name,
                    "formula": spec.formula,
                    "universe": spec.universe,
                    "status": "passed" if passed else "failed",
                    "values_ok": values_ok,
                    "has_reported_metrics": has_targets,
                    "metrics": {
                        "ic_mean": bt.ic_mean,
                        "ic_ir": bt.ic_ir,
                        "long_short_annual_return": bt.long_short_annual_return,
                        "sharpe_ratio": bt.sharpe_ratio,
                        "max_drawdown": bt.max_drawdown,
                    },
                    "reported_metrics": reported.model_dump() if has_targets else None,
                    "metric_deviations": deviation.metric_deviations,
                    "deviation_passed": deviation.passed,
                    "backtest_result_id": bt.id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            n_errors += 1
            factor_results.append(
                {
                    "name": name,
                    "status": "error",
                    "error": str(exc),
                }
            )

    total = len(factor_results)
    if n_errors == total:
        status = "error"
    elif n_passed == total:
        status = "passed"
    elif n_passed > 0:
        status = "partial"
    else:
        status = "failed"

    result: dict[str, Any] = {
        "report_id": report_id,
        "status": status,
        "factors": factor_results,
        "summary": {
            "total": total,
            "passed": n_passed,
            "failed": n_failed,
            "errors": n_errors,
        },
        "backtest_window": {"start": start.isoformat(), "end": end.isoformat()},
    }

    out = output_dir or (paths.data_dir / "benchmark" / report_id)
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / "result.json"
    from reproagent.utils.jsonutil import dumps as json_dumps

    out_path.write_text(json_dumps(result, indent=2), encoding="utf-8")
    result["output_path"] = str(out_path)
    return result


def run_benchmark_all(
    settings: Settings | None = None,
    *,
    benchmark_dir: Path | None = None,
    include_pending: bool = False,
) -> dict[str, Any]:
    """对 catalog 中非 pending（或全部）报告逐个运行 benchmark。"""
    settings = settings or Settings()
    root = benchmark_dir or _benchmark_dir()
    reports = load_catalog(root)
    results: list[dict[str, Any]] = []
    for r in reports:
        rid = r["report_id"]
        st = r.get("status", "pending")
        if not include_pending and st == "pending":
            continue
        gt_path = root / rid / "ground_truth.yaml"
        if not gt_path.exists():
            results.append({"report_id": rid, "status": "missing_ground_truth"})
            continue
        results.append(run_benchmark(rid, settings, benchmark_dir=root))

    n_ok = sum(1 for x in results if x.get("status") == "passed")
    return {
        "status": "passed" if n_ok == len(results) and results else "partial",
        "reports": results,
        "summary": {"total": len(results), "passed": n_ok},
    }
