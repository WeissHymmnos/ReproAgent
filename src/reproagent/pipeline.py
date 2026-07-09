"""端到端流程编排（masterplan §9）。

实现时按注释步骤填充；当前为桩，便于后续填空。
"""

from __future__ import annotations

from pathlib import Path

from reproagent.settings import Settings


def reproduce_report(pdf_path: Path, settings: Settings) -> None:
    """主入口：摄入 → 解析 → 复现 → 偏差 → 入库 / 反思 / 人工复核。

    流程映射：
    1. 子系统 1 摄入：upload_pdf → validate_pdf；invalid → review queue
    2. 缓存检查：compute_cache_key → CacheManager.get_cached / get_cached_backtest
    3. 子系统 2 解析：ReportParser.parse → build_config；低置信 → review queue
    4. 子系统 3 复现：FactorReproducer.reproduce
    5. 子系统 4 偏差：DeviationAnalyzer.analyze / classify_root_cause
       - passed → 子系统 5 入库 FactorLibraryManager.register
       - 未通过 → ReflectionLoopController.run 或 review queue
    6. 子系统 6 通知前端（CLI 打印 / TUI reactive）
    """
    raise NotImplementedError("pipeline.reproduce_report — 见 masterplan §9")
