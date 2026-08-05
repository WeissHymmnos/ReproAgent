# ReproAgent 技术指南

> 版本: 0.1.0 | 更新: 2026-08-05 | 行数: ~9,200 (核心) + ~2,500 (测试)
>
> 面向 AI Coding Agent 和开发者的完整技术参考文档，
> 覆盖架构、数据模型、算法、接口、配置、测试的每一个函数级细节。

---

## 目录

1. [项目定位与目标](#1-项目定位与目标)
2. [系统架构](#2-系统架构)
3. [数据模型](#3-数据模型)
4. [管线详解](#4-管线详解)
5. [PDF 解析层](#5-pdf-解析层)
6. [因子引擎](#6-因子引擎)
7. [回测引擎](#7-回测引擎)
8. [反过拟合套件](#8-反过拟合套件)
9. [数据加载与守卫](#9-数据加载与守卫)
10. [偏差分析与反思自愈](#10-偏差分析与反思自愈)
11. [经验记忆与知识积累](#11-经验记忆与知识积累)
12. [因子库管理](#12-因子库管理)
13. [CLI / TUI / MCP](#13-cli--tui--mcp)
14. [Multi-Agent 框架](#14-multi-agent-框架)
15. [配置参考](#15-配置参考)
16. [测试体系](#16-测试体系)

---

## 1. 项目定位与目标

### 1.1 核心使命

ReproAgent 是一个**量化研报因子自动复现系统**。
输入一篇中国 A 股卖方研报 PDF，输出：

1. **ParsedFactorSpec[]** — 研报中所有因子的结构化定义（公式、参数、输入字段）
2. **BacktestResult** — 每个因子的回测结果（IC、ICIR、分组收益、夏普、最大回撤等）
3. **DeviationReport** — 复现指标与研报声称指标的偏差分析
4. **FactorLibraryEntry** — 通过偏差门控的因子沉淀入库

### 1.2 设计原则

- **确定性优先**: 相同输入产生相同输出。Polars 引擎有 CI 确定性自检（10 个经典因子逐点比对）
- **离线可跑**: 无 LLM API、无网络时全链路可跑（Mock 模式 + Local 数据源）
- **防护纵深**: 数据守卫 → 未来函数检测 → 反过拟合套件 → 偏差门控 → 人工复核队列
- **渐进式复杂度**: dev 模式宽松容忍 → prod 模式严格阻断

### 1.3 与前沿项目的差异

| 维度 | ReproAgent | QuantaAlpha | QuantGPT | FactorMiner | zer0factor |
|------|-----------|-------------|----------|-------------|------------|
| 核心场景 | **研报复现** | 因子挖掘(进化) | 因子挖掘(Agent) | 因子挖掘(Ralph Loop) | 因子研究台 |
| 输入 | PDF 研报 | 研究方向文本 | 自然语言 | 操作符库 | 研报/想法 |
| 输出 | 验证因子+报告 | 进化因子库 | BRAIN提交因子 | 低冗余因子库 | 标准化因子 |
| 特殊性 | 偏差自愈+基准语料 | 轨迹进化 | 双模型交叉验证 | Skills+经验记忆 | FactorSpec+FactorFrame |


---

## 2. 系统架构

### 2.1 六层子系统

```
┌─────────────────────────────────────────────────────────┐
│                    CLI / TUI / MCP                       │
│   cli.py (Typer, 8 commands)                            │
│   tui/app.py (Textual)                                  │
│   mcp_server.py (FastMCP, 8 tools)                      │
├─────────────────────────────────────────────────────────┤
│                   Pipeline (管道编排)                    │
│   pipeline.py — reproduce_report() 端到端编排            │
│   调度: 摄入→解析→复现→偏差→入库                         │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Ingestion│  Parser  │Reproducer│Deviation │  Library    │
│ (摄入)   │ (解析)   │ (复现)   │ (偏差)   │  (因子库)   │
│          │          │          │          │             │
│ uploader │ layout_  │polars_   │ analyzer │ manager     │
│ validator│ extractor│ engine   │root_cause│ classifier  │
│ review_  │ llm_     │backtester│reflection│ versioning  │
│ queue    │ extractor│metrics   │_loop     │ index_writer│
│          │ schema_  │anti_over-│tolerances│ wiki_writer │
│          │ validator│ fitting  │          │ dashboard   │
│          │ prompts  │data_guard│          │ experience_ │
│          │report_   │lookahead │          │ memory      │
│          │ parser   │safe_eval │          │ decay_      │
│          │          │data_loadr│          │ monitor     │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│              Persistence (持久化) + Cache (缓存)          │
│   SQLModel tables + Repository + CacheManager            │
├─────────────────────────────────────────────────────────┤
│              Models (领域模型, 纯 Pydantic)               │
│   report, factor_spec, factor_def, replication,          │
│   backtest, comparison, deviation, reflection, library   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流向

```
PDF 文件
  │
  ├─[1. Ingestion]──→ ResearchReport (file_hash, page_count, validated)
  │
  ├─[2. Parser]─────→ finreportparser → Markdown
  │                └─→ LLMExtractor → ParsedFactorSpec[]
  │                └─→ SchemaValidator → [OK]/[WARN]
  │                └─→ ConfigBuilder → ReplicationConfig
  │
  ├─[3. Reproducer]─→ DataLoader → pl.DataFrame (量价+基本面)
  │                └─→ DataGuard → 过滤后数据
  │                └─→ LookaheadDetector → 未来函数报告
  │                └─→ PolarsEngine → factor_value DataFrame
  │                └─→ StrategyBacktester → BacktestResult
  │                └─→ AntiOverfittingSuite → DSR/PBO/...
  │
  ├─[4. Deviation]──→ DeviationAnalyzer → DeviationReport
  │                └─→ classify_root_cause → RootCause
  │                └─→ ReflectionLoopController → revised spec
  │
  └─[5. Library]────→ check_redundancy → OK/冗余
                   └─→ register → FactorLibraryEntry
                   └─→ update_index → INDEX.md
                   └─→ ExperienceMemory.record
```

### 2.3 包结构

```
src/reproagent/
├── __init__.py              # __version__
├── __main__.py              # python -m reproagent
├── cli.py                   # Typer CLI (8 命令, ~350 行)
├── pipeline.py              # 端到端编排 (~250 行)
├── settings.py              # pydantic-settings (~100 行)
├── exceptions.py            # 异常层级 (~50 行)
├── logging_setup.py         # loguru 配置
├── mcp_server.py            # FastMCP 8 工具 (~170 行)
├── api_models.py            # REST API 模型 (~40 行)
│
├── models/                  # Pydantic v2 领域模型
│   ├── report.py            # ResearchReport, ReportedMetrics
│   ├── factor_spec.py       # ParsedFactorSpec, FactorInputField, DataDictMapping
│   ├── factor_def.py        # FactorDefinition (规范化因子)
│   ├── replication.py       # ReplicationConfig, BacktestParams
│   ├── backtest.py          # BacktestResult (含反过拟合字段)
│   ├── comparison.py        # ComparisonReport
│   ├── deviation.py         # DeviationReport, ToleranceConfig, RootCause
│   ├── reflection.py        # ReflectionState, ReflectionStep
│   └── library.py           # FactorLibraryEntry, LibraryFilter
│
├── ingestion/               # 子系统1: 摄入与预处理
│   ├── uploader.py          # upload_pdf(path) → ResearchReport
│   ├── validator.py         # validate_pdf(report) → ResearchReport
│   └── review_queue.py      # enqueue/dequeue/confirm 人工复核
│
├── parser/                  # 子系统2: 研报解析
│   ├── protocol.py          # ReportParserProtocol
│   ├── layout_extractor.py  # finpdfpro → Markdown
│   ├── llm_extractor.py     # Vision LLM + Pydantic → ParsedFactorSpec[]
│   ├── schema_validator.py  # 校验 + 数据字典映射 [OK]/[WARN]
│   ├── config_builder.py    # ParsedFactorSpec[] → ReplicationConfig
│   ├── report_parser.py     # ReportParser 编排器
│   └── prompts.py           # Jinja2 提取/反思提示模板
│
├── reproducer/              # 子系统3: 因子复现
│   ├── protocol.py          # FactorReproducerProtocol, FactorEngine Protocol
│   ├── reproducer.py        # FactorReproducer 编排器 (~120 行)
│   ├── evaluator_factory.py # build_evaluator(config) → FactorEngine
│   ├── polars_engine.py     # PolarsEngine: 55+ 算子 AST 求值 (~700 行)
│   ├── rqalpha_engine.py    # RiceQuantEval 薄封装
│   ├── backtester.py        # StrategyBacktester: 分组回测+IC+中性化 (~220 行)
│   ├── data_loader.py       # 数据加载: local/ricequant/tushare/qlib (~620 行)
│   ├── data_guards.py       # ST/停牌/新股/涨跌停过滤器 (~240 行)
│   ├── lookahead_detector.py # AST 未来函数检测 (~200 行)
│   ├── anti_overfitting.py  # DSR/PBO/MinBTL/Bootstrap/WF/Placebo (~560 行)
│   ├── safe_eval.py         # 受限求值器 (~100 行)
│   └── metrics.py           # IC/分组/夏普/回撤/衰减/单调性 (~230 行)
│
├── deviation/               # 子系统4: 偏差控制与自愈
│   ├── protocol.py          # DeviationAnalyzerProtocol
│   ├── analyzer.py          # DeviationAnalyzer: 对比+容忍检查 (~80 行)
│   ├── tolerances.py        # ToleranceConfig 默认值
│   ├── root_cause.py        # 启发式+LLM 根因分类 (~120 行)
│   └── reflection_loop.py   # ReflectionLoopController: N≤3 自愈 (~180 行)
│
├── library/                 # 子系统5: 因子库管理
│   ├── protocol.py          # FactorLibraryProtocol
│   ├── manager.py           # FactorLibraryManager: register/get/list/check_redundancy
│   ├── versioning.py        # semver bump + dedup_hash
│   ├── classifier.py        # 风格自动分类
│   ├── index_writer.py      # 重生成全局 INDEX.md
│   ├── wiki_writer.py       # 逐因子 Markdown wiki 页
│   ├── dashboard.py         # HTML 仪表盘生成
│   ├── experience_memory.py # Ralph Loop 经验记忆 (~270 行)
│   └── decay_monitor.py     # Alpha 衰减监控 (~110 行)
│
├── persistence/             # 存储层
│   ├── db.py                # SQLModel engine/session 工厂
│   ├── tables.py            # SQLModel 表类
│   ├── repository.py        # 通用 CRUD
│   └── paths.py             # AppPaths 文件系统路径约定
│
├── cache/                   # 缓存层
│   ├── cache_manager.py     # CacheManager
│   └── cache_key.py         # compute_cache_key + compute_data_version
│
├── tui/                     # 子系统6: 前端
│   ├── app.py               # ReproAgentApp (Textual)
│   ├── commands.py          # 命令面板
│   ├── screens/             # reproduction, library_browser, review
│   └── widgets/             # factor_tree, deviation_gauge, log_panel
│
├── agents/                  # Multi-Agent 框架 (骨架)
│   └── __init__.py          # 5 角色: Hypothesis, Factor, Backtest, Review, Curator
│
└── utils/
    ├── hashing.py           # sha256_file, content_hash
    ├── pdf.py               # get_page_count, is_readable, has_pdf_header
    └── plotting.py          # matplotlib 图表 → PNG
```

---

## 3. 数据模型

所有模型均为 Pydantic v2 `BaseModel`，跨 LLM/YAML/DB 三界序列化。

### 3.1 ResearchReport (report.py)

```python
class ResearchReport(BaseModel):
    id: str                              # UUID4 hex
    file_path: Path                      # 原始 PDF 位置
    file_hash: str                       # PDF 字节 SHA256
    title: str | None = None
    author: str | None = None
    broker: str | None = None            # 如 "中信证券"
    report_date: date | None = None
    page_count: int
    validation_status: Literal["pending", "valid", "invalid"] = "pending"
    validation_errors: list[str] = []
    ingested_at: datetime                # UTC
```

**生命周期**: `upload_pdf()` 创建 → `validate_pdf()` 设置 validation_status → `save_report()` 持久化。

### 3.2 ParsedFactorSpec (factor_spec.py)

LLM 从研报提取的原始因子定义。一个 `ParsedFactorSpec` 对应研报中描述的一个因子。

```python
class FactorInputField(BaseModel):
    name: str              # 规范化名, 如 "turnover_rate"
    report_name: str       # 研报原文术语, 如 "换手率"
    data_type: Literal["price","volume","fundamental","macro","derived"]
    description: str = ""
    frequency: Literal["daily","weekly","monthly","quarterly","annual"] = "daily"

class DataDictMapping(BaseModel):
    report_term: str       # "换手率"
    canonical_term: str    # "turnover_rate"
    confidence: float      # 0.0-1.0, ≥0.8 → OK
    tag: Literal["OK","WARN"]
    note: str | None = None

class ParsedFactorSpec(BaseModel):
    id: str
    factor_name: str
    factor_name_cn: str
    description: str
    formula: str           # LaTeX 或伪代码
    input_fields: list[FactorInputField]
    computation_steps: list[str]
    rebalance_frequency: Literal["daily","weekly","monthly","quarterly"] = "monthly"
    universe: str = "全A股"
    lookback_window: int | None = None
    data_dict_mappings: list[DataDictMapping] = []
    extraction_confidence: float          # 0.0-1.0
    source_pages: list[int] = []
    reported_metrics: ReportedMetrics | None = None
```

### 3.3 FactorDefinition (factor_def.py)

规范化、可计算的因子定义。由 `ParsedFactorSpec` 通过 `_build_factor_def()` 构建。

```python
class FactorDefinition(BaseModel):
    id: str
    spec_id: str                         # FK → ParsedFactorSpec.id
    name: str
    name_cn: str
    style: Literal["value","growth","momentum","quality","size",
                   "volatility","liquidity","macro","technical","other"]
    formula: str                         # 可求值的 Polars 表达式
    input_fields: list[str]              # 规范化字段名
    computation_code: str | None = None
    universe: str
    rebalance_frequency: str
    version: str = "0.1.0"              # semver
    lookahead_risk: bool = False         # 是否检测到未来函数
    data_guard_applied: bool = False     # 是否应用数据守卫
    adjustment_type: str = "forward"     # 复权类型
```

### 3.4 BacktestResult (backtest.py)

```python
class BacktestResult(BaseModel):
    id: str
    config_id: str
    factor_id: str
    engine: str
    start_date: date
    end_date: date
    # 核心指标
    group_annualized_returns: dict[int, float] = {}
    ic_mean: float
    ic_ir: float
    long_short_annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    turnover: float
    factor_values_path: Path
    equity_curve_path: Path
    computed_at: datetime
    # 反过拟合 (Phase 2)
    dsr: float | None = None
    dsr_pvalue: float | None = None
    pbo: float | None = None
    min_btl: int | None = None
    sharpe_ci_lower: float | None = None
    sharpe_ci_upper: float | None = None
    walk_forward_ic_oos: float | None = None
    regime_ics: dict[str, float] = {}
    placebo_pvalue: float | None = None
    alpha_decay: dict[int, float] = {}
    monotonicity: float | None = None
    half_life: float | None = None
```

### 3.5 ToleranceConfig (deviation.py)

```python
class ToleranceConfig(BaseModel):
    # 核心指标容忍区间
    ic_mean_abs: float = 0.03
    ic_ir_abs: float = 0.2
    long_short_return_rel: float = 0.15
    sharpe_abs: float = 0.3
    max_drawdown_abs: float = 0.05
    # 反过拟合门控 (Phase 2)
    min_dsr: float = -1.0
    max_pbo: float = 0.3
    min_sharpe_ci_lower: float = 0.0
    min_walk_forward_ic: float = 0.0
    require_placebo_significant: bool = True
```

### 3.6 其他模型

| 模型 | 文件 | 用途 |
|------|------|------|
| `ReplicationConfig` | replication.py | 一次复现的完整配置 (因子+回测参数+引擎选择) |
| `BacktestParams` | replication.py | 回测参数 (起止日/初始资金/基准/分组数/费率) |
| `ComparisonReport` | comparison.py | 复现值 vs 研报声称值 对比 |
| `DeviationReport` | deviation.py | 偏差分析结果 (passed/root_cause/metric_deviations) |
| `ReflectionState` | reflection.py | 反思循环状态 (迭代数/最佳偏差/状态机) |
| `ReflectionStep` | reflection.py | 反思循环中一次迭代的记录 |
| `FactorLibraryEntry` | library.py | 因子库记录 (dedup_hash/status/version/tags) |
| `LibraryFilter` | library.py | 因子库过滤条件 (style/status/broker/tags) |
| `RootCause` (enum) | deviation.py | DATA_MISMATCH/FORMULA_ERROR/PARAMETER_ERROR/UNIVERSE_MISMATCH/LOOKAHEAD_BIAS/UNKNOWN |

---

## 4. 管线详解

### 4.1 pipeline.py — reproduce_report()

端到端编排函数，是 CLI `reproduce` 命令的核心。

```python
def reproduce_report(pdf_path: Path, settings: Settings) -> dict:
```

**流程**:

1. **摄入验证**: `upload_pdf(pdf_path)` → `validate_pdf(report)`
2. **解析**: `ReportParser(settings).parse(report)` → `ParsedFactorSpec[]`
3. **逐因子处理** (`_process_one_factor`):
   a. `ConfigBuilder.build_config([spec], report)` → `ReplicationConfig`
   b. `FactorReproducer.reproduce(config)` → `BacktestResult`
   c. `DeviationAnalyzer.analyze(result, reported, tolerances)` → `DeviationReport`
   d. 若 passed → `FactorLibraryManager.register(entry)` → 入库
   e. 若 not passed → `ReflectionLoopController.run(config, reported)` → 反思循环
4. **汇总返回** `dict`: status + factors 列表

### 4.2 状态机

```
                   ┌─────────┐
                   │  START  │
                   └────┬────┘
                        ↓
              ┌─────────────────┐
              │  parse (提取)    │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │  reproduce (复现)│
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │  deviation check │
              └───┬─────────┬───┘
          passed  │         │  not passed
                  ↓         ↓
         ┌──────────┐  ┌──────────────┐
         │ register │  │  reflection   │
         │  (入库)   │  │  loop (≤3次)  │
         └──────────┘  └──┬───────┬───┘
                          │       │
                     converged escalated/exhausted
                          │       │
                          ↓       ↓
                     register  review_queue
```


---

## 5. PDF 解析层

### 5.1 架构概览

ReproAgent 使用 vendored 的 `finreportparser` 作为唯一 PDF 后端。

```
PDF → finreportparser.parse_pdf()
    ├─ 逐页文本提取 (PyMuPDF)
    ├─ 页面分类 (page_router)
    ├─ OCR (PaddleOCR/Unlimited-OCR)
    ├─ 表格提取 (text-layer tables / PP-Structure / MinerU)
    ├─ 图表理解 (VLM classify-first)
    ├─ 页眉页脚过滤
    ├─ 跨页表格拼接
    ├─ 公式识别与提升
    └─ 文档重建

→ DocumentResult
  ├─ pages: list[PageResult] (blocks, tables, images)
  ├─ metrics: list[MetricItem]
  ├─ charts: list[ChartMeta]
  ├─ mermaid: list[str]
  ├─ toc: list[TocEntry]
  └─ quality: QualityReport

→ render_markdown(doc) → Markdown 文本
```

### 5.2 LayoutExtractor (layout_extractor.py)

```python
class LayoutExtractor:
    def __init__(self, backend: Literal["finpdfpro","marker","llamaparse","mineru"] = "finpdfpro",
                 settings: Settings | None = None)
    def extract(self, report: ResearchReport) -> str:  # → Markdown
```

当前仅支持 `finpdfpro`。其他后端会抛出 `ConfigurationError`。

`extract()` 流程:
1. 懒导入 `finreportparser`
2. 从 `settings.finpdfpro_mode` 加载配置
3. 从 `settings.finpdfpro_vlm_backend` 设置 VLM 后端
4. 调用 `finreportparser.parse_pdf(report.file_path, config=config)`
5. 通过 `render_markdown(doc)` 生成 Markdown
6. 捕获 `CorruptPdfError` → `ParseError`

### 5.3 finreportparser 关键模块

| 模块 | 功能 |
|------|------|
| `pipeline/orchestrator.py` | `parse_pdf()`, `parse_pdf_to_files()` — 端到端入口 |
| `pipeline/page_router.py` | `route_page()` — 页面分类，决定哪些引擎运行 |
| `pipeline/reconstruct.py` | 阅读顺序排序、文本/表格去重、公式提升 |
| `extract/pdf_text.py` | PyMuPDF 文本层提取 + 乱码检测 |
| `extract/text_tables.py` | 零 GPU 文本层表格提取 (词框→行聚类→列间隙→GFM) |
| `extract/pdf_images.py` | 图片区域提取、整页渲染 |
| `ocr/base.py` | `OcrEngine`, `BaseTableExtractor` 协议 |
| `ocr/paddle_ocr.py` | PaddleOCR 实现 |
| `ocr/structure.py` | PP-StructureV2/V3 表格提取 |
| `vlm/base.py` | `BaseVLMProvider` 协议 |
| `vlm/chart_understanding.py` | classify-first 图表理解管线 |
| `vlm/edge_hybrid.py` | SmolVLM-256M 分类 + PaddleOCR 描述融合 |
| `fusion/table_repair.py` | GFM 表格修复 (676 行，粘合表头、OCR 混淆词、列重对齐) |
| `fusion/table_quality.py` | 表格接受/拒绝评分门控 |
| `fusion/headers_footers.py` | 券商免责声明/页码过滤 |
| `fusion/tables_cross_page.py` | 跨页表格拼接 |
| `fusion/metrics.py` | 财务指标正则提取 |
| `fusion/formula_detect.py` | 公式检测 + LaTeX 近似 |

### 5.4 三档质量模式

| 模式 | VLM | OCR | 表格 | 速度 |
|------|-----|-----|------|------|
| `fast` | none | 仅乱码页 | text-layer tables | 最快 |
| `balanced` | none | 需要时 | text-layer + PP-Structure fallback | 均衡 |
| `max-quality` | 启用 | 全页 | PP-Structure + VLM 图表 | 最慢 |

### 5.5 内存治理

`utils/memory.py` — 协驻留矩阵限制同时加载的重型模型数，worker 上限控制，~16 GB RAM 目标。重型引擎 (OCR, structure, VLM) 每 parse 实例化一次，跨页共享，结束后卸载。

---

## 6. 因子引擎

### 6.1 PolarsEngine (polars_engine.py)

核心因子计算引擎，~700 行，55+ 算子。通过 AST 解析动态求值。

```python
class PolarsEngine:
    def __init__(self, config: ReplicationConfig, *, allow_formula_fallback: bool = False)
    def compute(self, factor_def: FactorDefinition, universe: str,
                start: date, end: date, data: pl.DataFrame | None = None) -> pl.DataFrame:
        # 返回 [date, asset, factor_value]
    def _eval_ast_node(self, node: ast.AST, df_container: list[pl.DataFrame],
                       tmp_cols: list[str]) -> Any:
        # 递归 AST 解释器
```

#### compute() 算法

1. **列名规范化**: `trade_date`→`date`, `ts_code`→`asset`
2. **公式预处理**: 移除 `$field` 前缀 (`$close`→`close`)
3. **AST 解析**: `ast.parse(formula, mode="eval")`
4. **AST 求值**: `_eval_ast_node(tree.body, ...)` — 生成 Polars 表达式
5. **表达式应用**: `df.with_columns(pl_expr.alias("factor_value"))`
6. **临时列清理**: 移除 CS 算子物化产生的中间列
7. **输出**: `select(["date", "asset", "factor_value"]).drop_nulls()`
8. **错误处理**: SyntaxError → allow_formula_fallback ? 回退到 close : raise FormulaError

#### _eval_ast_node() 递归算法

```
eval(node):
  Constant → node.value
  Name     → _CONTEXT.get(id, pl.col(id))
  BinOp    → eval(left) op eval(right)
  Call     →
    func = _CONTEXT[func_name]
    args = [eval(a) for a in node.args]
    if is_cross_sectional and not bare_col:
      # 物化中间表达式为临时列
      tmp = f"__cs_arg_{N}__"
      df.with_columns(arg_val.alias(tmp))
      arg_val = pl.col(tmp)
    return func(*args)
```

#### 算子完整签名

**截面算子** (按 date 分组):
- `Rank(x, n=None)` — rank/count，返回 (0,1]
- `CSRank(x)` — 同 Rank
- `CSZScore(x, n=None)` — cross-sectional z-score (mean=0, std=1)
- `GroupNeutral(x)` — 减去截面均值
- `Winsorize(x, pct=0.05)` — 分位数 clip
- `Percentile(x)` — 截面百分位
- `Scale(x, a=1)` — 缩放到 sum(abs)=a

**时序算子** (按 asset 分组):
- `Ref(x, n)` — n 天前的值 (shift)
- `Delta(x, n)` — n 天变化 = x - Ref(x, n)
- `Mean(x, n)` — n 天滚动均值
- `Std(x, n)` — n 天滚动标准差
- `Median(x, n)` — n 天滚动中位数
- `Sum(x, n)` — n 天滚动和
- `EMA(x, n)` — span=n 指数移动平均
- `WMA(x, n)` — 线性加权移动平均
- `Var(x, n)` — n 天滚动方差
- `Skew(x, n)` — n 天滚动偏度
- `Kurt(x, n)` — n 天滚动峰度
- `Mad(x, n)` — n 天滚动中位绝对偏差
- `Ts_Rank(x, n)` — 时序百分位排名
- `Ts_Max(x, n)` — n 天滚动最大值
- `Ts_Min(x, n)` — n 天滚动最小值
- `Ts_ArgMax(x, n)` — 距离 n 天内最大值的天数
- `Ts_ArgMin(x, n)` — 距离 n 天内最小值的天数
- `Ts_Percentile(x, n, p=50)` — n 天滚动 p-th 百分位数
- `Count(x=None)` — 非 null 计数

**关联算子** (时序，按 asset):
- `Corr(x, y, n)` — n 天滚动相关系数
- `Cov(x, y, n)` — n 天滚动协方差
- `Correlation(x, y, n)` — Corr 别名

**数学算子** (逐元素):
- `Abs(x)`, `Log(x)`, `Sign(x)`, `Sqrt(x)`
- `Exp(x)`, `Pow(x, n)`, `Neg(x)`, `Inv(x)`
- `Ceil(x)`, `Floor(x)`

**逻辑算子**:
- `If(cond, a, b)` — if-then-else
- `Greater(a,b)`, `Less(a,b)`, `GreaterEqual(a,b)`, `LessEqual(a,b)`
- `Equal(a,b)`, `NotEqual(a,b)`
- `And(*args)`, `Or(*args)`, `Not(a)`
- `Clip(x, lower, upper)` — 值截断

**算术及别名**:
- `Add/Sub/Mul/Div` (主) + `Plus/Minus/Multiply/Divide/Subtract/Divi` (别名)
- `Max(a,b)`, `Min(a,b)`
- `Mult`(Mul别名), `Negate`(Neg别名), `Correlation`(Corr别名)
- `Const(x)` — 字面量包装

**字段白名单**:
`close, open, high, low, volume, amount, $close, $open, $high, $low, $volume, $vwap, trade_date, date, asset, ts_code`

### 6.2 表达式校验器

```python
def validate_expression(expr: str) -> dict:
    # → {"valid": bool, "errors": list[str], "warnings": list[str]}
```

校验规则:
1. 括号平衡检查
2. AST 解析 (SyntaxError → invalid)
3. 算子白名单 (未知算子 → error)
4. Ref/Delta 负窗口 (n<0 → error)
5. Corr/Cov 自相关 (a==a → error)
6. Div(x,x) 同义反复 (→ error)
7. 裸价格字段引用 (close/open/high/low 未滞后 → warning)

### 6.3 安全求值器 (safe_eval.py)

```python
def safe_eval(source: str | ast.AST, context: Mapping[str, Any] | None = None) -> Any
```

从 aiminer 移植。禁止 `__import__`, `eval`, `exec`, `open`, `getattr`, `globals`, `type`, `print` 等 48 个危险名称。空 `__builtins__`。独立工具，当前未被 PolarsEngine 默认使用（PolarsEngine 使用自己的 AST 解释器）。

---

## 7. 回测引擎

### 7.1 StrategyBacktester (backtester.py)

```python
class StrategyBacktester:
    def __init__(self, settings: Settings) -> None
    def run(self, factor_values: pl.DataFrame, params: BacktestParams,
            factor_def: FactorDefinition, data: pl.DataFrame | None = None) -> BacktestResult
```

#### run() 算法

1. **数据加载** (若未提供):
   - `DataLoader.load_price_data(universe, start, end)`
2. **列名规范化**: `date`→`trade_date`, `asset`→`ts_code`
3. **前向收益计算**:
   ```python
   forward_return = close.shift(-1).over(ts_code) / close - 1
   ```
4. **Rank IC**:
   - 按 date 分组，计算 `corr(factor_value, forward_return, method='spearman')`
   - `ic_mean = mean(ic)`, `ic_ir = ic_mean / std(ic)`
5. **分组赋值**:
   ```python
   rank = factor_value.rank(method='ordinal').over(date)
   group = floor(rank / (max(rank)+1) * num_groups)
   ```
6. **分组年化收益**: 各 group 的日度等权收益均值 × 252
7. **多空组合**:
   - long: group N-1 (最高因子值组), short: group 0 (最低组)
   - 等权: ±1/count per group
   - 换手: `sum(|w_t - w_{t-1}|) / 2` per date, 平均得单边换手
   - 扣费: `ls_return = ls_return_raw - turnover * cost_bps / 10000`
8. **指标计算**:
   - Sharpe: `mean(ls_return) / std(ls_return) * sqrt(252)`
   - 最大回撤: `max((cummax - cum) / cummax)`
   - 年化收益: `mean(ls_return) * 252`
9. **持久化**:
   - `data_dir/backtest/{factor_id}/factor_values.parquet`
   - `data_dir/backtest/{factor_id}/equity_curve.parquet`
   - `data_dir/backtest/{factor_id}/ic.parquet`
10. **返回** `BacktestResult` (含所有计算指标)

### 7.2 中性化函数

```python
def neutralize_industry(factor: pl.Series, industry: pl.Series) -> pl.Series:
    """factor ~ industry_dummies → residuals"""

def neutralize_market_cap(factor: pl.Series, log_mcap: pl.Series) -> pl.Series:
    """factor ~ [1, log_mcap] OLS → residuals via np.linalg.lstsq"""
```

### 7.3 指标函数 (metrics.py)

| 函数 | 签名 | 算法 |
|------|------|------|
| `compute_ic` | `(factor_values, forward_returns) → pl.DataFrame` | 截面 Spearman rank corr per date |
| `compute_group_returns` | `(grouped, returns, num_groups) → dict[int,float]` | 各组日度等权收益均值 × 252 |
| `compute_sharpe` | `(returns, freq="daily") → float` | mean/std × √252 |
| `compute_max_drawdown` | `(equity_curve) → float` | max(1 - cum/max(cum)) |
| `compute_alpha_decay` | `(fv, fwd_ret, lags=[1,2,3,5,10,20]) → dict[int,float]` | 各 lag 的 mean rank IC |
| `compute_monotonicity` | `(grouped_returns) → float` | 逐日 Kendall tau 均值 |
| `compute_half_life` | `(ic_series) → float` | \|IC\| < \|IC₀\|/2 的 lag，或指数拟合 |
| `generate_charts` | `(bt_result, output_dir) → list[Path]` | group_returns.png + equity_curve.png + ic_timeseries.png |

---

## 8. 反过拟合套件

### 8.1 概览

`anti_overfitting.py` 实现 7 项统计检验（~560 行），参考 alpha-lens / QuantGPT。

### 8.2 Deflated Sharpe Ratio (DSR)

```python
def deflated_sharpe_ratio(sharpe, n_trials, n_obs, sharpe_std=None,
                          skew=0.0, kurt=3.0) -> DSRResult
```

**算法**:
1. 若 `sharpe_std` 未提供: `std ≈ sqrt((1 + 0.5*S² - γ₁*S + (γ₂-1)/4 * S²) / (n-1))`
2. 期望最大 Sharpe (E[max]): `std * sqrt(2 * ln(n_trials))`
3. PSR = `Φ(sharpe / std)`
4. DSR = `Φ((sharpe - E[max]) / std)`
5. p-value = `1 - DSR`
6. `deflated = DSR < 0.05`

### 8.3 Probability of Backtest Overfitting (PBO)

```python
def prob_backtest_overfitting(returns, n_splits=5, oos_ratio=0.3) -> PBOResult
```

**算法** (Combinatorial Purged Cross-Validation):
1. 将 returns 分为 `n_splits` 段时间段
2. 生成 C(n_splits, n_splits//2) 种 IS/OOS 组合
3. 每种组合: IS Sharpe 和 OOS Sharpe
4. PBO = (1 - Kendall τ(IS ranks, OOS ranks)) / 2
5. `overfit = PBO > 0.5`

### 8.4 其他检验

| 检验 | 函数 | 关键参数 |
|------|------|----------|
| MinBTL | `min_backtest_length(sharpe, variance, alpha)` | n = ceil(v·(Φ⁻¹(1-α/2))² / daily_sharpe²) |
| Bootstrap CI | `bootstrap_sharpe_ci(returns, n_boot=2000, alpha=0.05)` | 百分位法 |
| Walk-Forward | `walk_forward_validation(fv, fwd_ret, n_splits=5, method="expanding")` | 逐日 Spearman IC per split |
| Stress Test | `subsample_stress_test(df, returns_col, index_returns_col)` | bull(>2σ)/bear(<-2σ)/sideways |
| Placebo | `placebo_test(fv, fwd_ret, n_shuffles=100)` | 随机打乱因子值，双尾 z-test |

---

## 9. 数据加载与守卫

### 9.1 DataLoader (data_loader.py)

```python
class DataLoader:
    def __init__(self, settings: Settings) -> None
    def load_price_data(self, universe, start, end) -> pl.DataFrame
    def load_fundamental_data(self, fields, start, end) -> pl.DataFrame
```

**四后端架构**:

| 后端 | 量价实现 | 基本面实现 |
|------|---------|-----------|
| `local` | 读取 `prices.parquet` / `prices.csv` | 读取 `fundamentals.parquet` |
| `ricequant` | `rqdatac.get_price()` | `rqdatac.get_factor()` |
| `tushare` | `pro.daily()` 逐日/逐股 | `pro.daily_basic()` + `pro.fina_indicator()` |
| `qlib` | `D.features()` | `D.features()` with `$` prefix |

**字段映射表** (研报术语 → 规范化):
```python
FUNDAMENTAL_FIELD_MAP = {
    "pe"/"市盈率": "pe_ttm", "pb"/"市净率": "pb",
    "roe"/"净资产收益率": "roe_ttm", "换手率": "turnover_rate",
    "市值": "market_cap", "流通市值": "float_market_cap",
    "营收增速": "revenue_yoy", "净利润增速": "profit_yoy",
    # ... ~30 个常见字段
}
```

### 9.2 数据口径守卫 (data_guards.py)

```python
def apply_guards(df, config=None) -> tuple[pl.DataFrame, DataGuardStats]
```

**过滤管线**:
1. `_normalize_columns` — 列名统一 (date→trade_date, instrument→ts_code)
2. `_filter_st` — 正则 `(?i)(?:\*?ST|ST\*|\*ST)` 匹配 name/ts_code
3. `_filter_suspended` — volume > 0, status != "suspended"
4. `_filter_new_listings` — trade_date − list_date ≥ min_listing_days
5. `_filter_limit_hit` — 合成 pre_close，排除涨跌停 (±9.8%)
6. `validate_adjustment` — 检查复权因子方差 / 收益率跳变

### 9.3 未来函数检测 (lookahead_detector.py)

```python
def detect_lookahead(formula: str) -> LookaheadReport
```

**两层检测**:
1. **文本层**: 正则匹配 `shift(-` (error), `lead(` (error)
2. **AST 层**: `_LookaheadVisitor` 遍历 AST
   - `Ref(x, n)` / `Delta(x, n)` 其中 n<0 → error "negative_window"
   - `.shift()` / `.lead()` 属性访问 → warning "shift_or_lead"
   - `close/open/high/low` 裸 Name 节点 → warning "unlagged_price"

**风险等级**: high (有 error) / medium (≥2 warnings) / low (1 warning) / none

---

## 10. 偏差分析与反思自愈

### 10.1 DeviationAnalyzer (analyzer.py)

```python
class DeviationAnalyzer:
    def analyze(self, reproduced, reported, tolerances) -> DeviationReport
    def classify_root_cause(self, deviation, config) -> RootCause
    def should_reflect(self, deviation, state) -> bool
```

#### analyze() 容忍区间

| 指标 | 容忍 | 类型 |
|------|------|------|
| ic_mean | ≤0.03 | 绝对偏差 |
| ic_ir | ≤0.2 | 绝对偏差 |
| long_short_return | ≤15% | 相对偏差 (分母=0时降级为≤5%绝对) |
| sharpe_ratio | ≤0.3 | 绝对偏差 |
| max_drawdown | ≤0.05 | 绝对偏差 |

### 10.2 根因分类 (root_cause.py)

```python
def classify_root_cause(deviation, config, *, use_llm_fallback=True) -> RootCause
```

**规则级联 (优先级降序)**:
1. IC+ICIR 同向大幅偏差 → `LOOKAHEAD_BIAS`
2. ≥3 指标同向偏差 → `DATA_MISMATCH`
3. IC 在容忍内但 Sharpe/LS 大幅偏差 → `PARAMETER_ERROR`
4. IC 大幅偏差但其他指标在容忍内 → `FORMULA_ERROR`
5. IC+Sharpe 同向大幅偏差 → `UNIVERSE_MISMATCH`
6. 统计显著 (bootstrap t-test > 2) + LLM fallback 启用 → `_llm_classify_root_cause`
7. 其他 → `UNKNOWN`

### 10.3 ReflectionLoopController (reflection_loop.py)

```python
class ReflectionLoopController:
    def __init__(self, reproducer, analyzer, llm_extractor,
                 config_builder, tolerances, repository, experience_memory=None)
    def run(self, initial_config, reported) -> ReflectionState
```

**有界反思循环算法**:
```
state = ReflectionState(status="in_progress", max_iterations=3)
while iteration < 3 and in_progress:
    result = reproducer.reproduce(config)
    deviation = analyzer.analyze(result, reported, tolerances)
    deviation.root_cause = classifier(deviation, config)

    if deviation.passed:
        state.status = "converged"
    elif no_improvement_streak >= 1:
        state.status = "escalated"

    if converged or escalated: break

    prompt = build_reflection_prompt(state, deviation)
    revised_spec = llm_extractor.revise(prompt, spec)
    config.factor_specs = [revised_spec]
    iteration += 1

if still in_progress:
    state.status = "exhausted"
```

**偏差评分**: `_deviation_score = sqrt(Σ(delta_i / tolerance_i)²)` — 归一化 RMS。

---

## 11. 经验记忆与知识积累

### 11.1 ExperienceMemory (experience_memory.py)

实现 **Ralph Loop** 范式 (retrieve → generate → evaluate → distill)。

```python
class ExperienceMemory:
    def record_success(formula, input_fields, style, ic, report_id) → SuccessfulPattern
    def record_failure(formula, input_fields, failure_mode, deviation_values, report_id) → FailedPattern
    def query_similar(formula, input_fields, top_k=5) → dict[str, list]
    def learn_term_mapping(report_term, canonical_term, confidence) → TermMapping
    def get_term_mapping(report_term) → TermMapping | None
    def build_reflection_context(formula, input_fields) → str
    def get_category_stats(style=None) → dict
```

**相似度算法**:
```
similarity(tpl_a, fields_a, tpl_b, fields_b):
    template_score = 1.0 (exact) / 0.7 (substring) / 0.0 (mismatch)
    field_overlap = |fields_a ∩ fields_b| / |fields_a ∪ fields_b|
    return 0.6 * template_score + 0.4 * field_overlap
```

**公式模版化**: 将公式中的数字替换为 `N`，去除空白 → 参数化模版 (如 `close/Ref(close,20)-1` → `close/Ref(close,N)-1`)

### 11.2 DecayMonitor (decay_monitor.py)

```python
class DecayMonitor:
    def check_factor(factor_id, original_ic, current_ic) → DecayStatus
    def check_all(factors: dict[str, tuple[float, float]]) → list[DecayStatus]
    def generate_report() → DecayReport
    def mark_deprecated_if_decayed(factor_id, original_ic, current_ic) → bool
```

衰减阈值: ic_drop > 0.5 → deprecated, > 0.3 → decaying, else stable.

---

## 12. 因子库管理

### 12.1 FactorLibraryManager (manager.py)

```python
class FactorLibraryManager:
    def register(entry, check_redundancy=True) → FactorLibraryEntry
    def check_redundancy(factor_values, max_correlation=0.7) → dict
    def get(factor_id) → FactorLibraryEntry | None
    def list(filter=None) → list[FactorLibraryEntry]
    def dedup_check(entry) → FactorLibraryEntry | None
```

#### register() 流程
1. 计算 `dedup_hash = sha256(formula | sorted(input_fields))`
2. `dedup_check` — 若已存在同 hash 条目 → bump patch 版本号，复用 ID
3. `classifier.classify` — 覆盖 entry.factor.style
4. `repository.save_library_entry` — 持久化到 SQLite
5. `index_writer.update` — 重建 `wiki/INDEX.md`
6. `wiki_writer.update` — 重建 `wiki/factors/{name}.md`

#### check_redundancy() 流程
1. 遍历库内所有因子 (来自 `list_library_entries`)
2. 读取每个因子的 `factor_values.parquet`
3. 对新旧因子值做 inner join (date+asset)
4. 计算截面 Pearson 相关系数
5. |corr| > max_correlation → 标记为冗余

### 12.2 支持模块

| 模块 | 功能 |
|------|------|
| `classifier.py` | 规则优先风格分类：关键词匹配 (mom/动量→momentum, value/pe/pb→value, ...) + LLM fallback |
| `versioning.py` | `compute_dedup_hash`: sha256(公式\|排序字段); `bump`: semver 递增 |
| `index_writer.py` | 重生成 `wiki/INDEX.md` 因子索引表 |
| `wiki_writer.py` | 逐因子 `wiki/factors/{name}.md` Markdown wiki 页 |
| `dashboard.py` | 单文件 HTML 仪表盘 (Chart.js CDN, 搜索/筛选, 模态图表) |


---

## 13. CLI / TUI / MCP

### 13.1 CLI (cli.py)

Typer 应用，8 个命令全部通过 `@app.command()` 注册。

| 命令 | 函数 | 关键参数 |
|------|------|----------|
| `ingest` | `ingest(pdf_path)` | 上传→校验→入库；invalid 自动入复核队列 |
| `reproduce` | `reproduce(pdf_path)` | 端到端管线；prod 强制 LLM key |
| `library` | `library(style, html)` | 列表+筛选；`--html` 生成仪表盘 |
| `review` | `review(list, approve, reject)` | 复核队列管理 |
| `tui` | `tui()` | 启动 Textual 界面 |
| `benchmark` | `benchmark(list, run, run_all, report)` | 基准语料管理 |
| `mcp` | `mcp()` | 启动 MCP 服务器 |
| `--version` | `_version_callback` | 打印版本号 |

所有命令共享 `_build_repository()` 和 `_build_library_manager()` 工厂函数。

### 13.2 TUI (tui/)

基于 Textual 框架的三页签界面。

```
ReproAgentApp (app.py)
├── Header
├── TabbedContent
│   ├── TabPane "复现" → ReportReproductionScreen
│   │   ├── Input (PDF 路径)
│   │   ├── Button "运行复现"
│   │   └── RichLog (JSON 结果输出)
│   ├── TabPane "因子库" → FactorLibraryScreen
│   │   ├── Button "刷新"
│   │   ├── Tree (风格→因子层级)
│   │   └── Markdown (因子详情)
│   └── TabPane "人工复核" → ManualReviewScreen
│       ├── Button "刷新"/"批准"/"拒绝"
│       └── Static (状态显示)
└── Footer
```

所有重型操作通过 `anyio.to_thread.run_sync` 在后台线程执行，不阻塞 UI。

快捷键: `q` 退出, `d` 切换主题, `r/l/v` 切换页签。

### 13.3 MCP 服务器 (mcp_server.py)

```python
def build_mcp_server() -> FastMCP
```

8 个 MCP 工具供 Claude Code / Claude Desktop 调用：

| 工具 | 参数 | 功能 |
|------|------|------|
| `validate_expression` | `expression: str` | 校验因子表达式白名单合规性 |
| `list_operators` | — | 列出所有 55+ 算子名和类型 |
| `run_backtest` | `expression, start_date, end_date, universe, num_groups` | 表达式→回测 |
| `score_factor` | `expression?, backtest_id?` | 多维评分 (骨架) |
| `diagnose_factor` | `expression: str` | 校验+未来函数检测 |
| `run_anti_overfitting` | `backtest_id?` | 4 项反过拟合检验 (骨架) |
| `list_universes` | — | csi300/csi500/csi1000/all |
| `search_factor_library` | `query?, style?` | 搜索因子库 (基础) |

启动: `uv run reproagent mcp`

Claude Desktop 配置:
```json
{"mcpServers": {"reproagent": {
    "command": "uv", "args": ["run", "reproagent", "mcp"]
}}}
```

### 13.4 REST API 模型 (api_models.py)

纯 Pydantic 模型，用于未来 REST API 实现：

| 模型 | 字段 |
|------|------|
| `BacktestRequest` | expression, start_date, end_date, universe, num_groups |
| `BacktestResponse` | job_id, status, result |
| `IngestResponse` | report_id, status, factors_found |
| `FactorSummary` | id, name, style, status, version |
| `FactorListResponse` | total, factors: list[FactorSummary] |
| `BenchmarkResponse` | report_id, status, factor_count |

---

## 14. Multi-Agent 框架

### 14.1 设计蓝图 (agents/__init__.py)

参考 QuantaAlpha-claw 蜂群架构和 FactorMiner Ralph Loop。5 个 Agent 角色：

```
HypothesisAgent.generate(report_text) → list[HypothesisResult]
    ↓
FactorAgent.synthesize(hypothesis) → FactorSynthesisResult
    ↓
BacktestAgent.evaluate(expression) → BacktestEvaluation
    ↓
ReviewAgent.review(hypothesis, synthesis, evaluation) → ReviewVerdict
    ↓
CuratorAgent.decide(evaluation, review, correlations) → CuratorDecision
```

当前为接口契约和骨架实现，完整编排留作后续迭代。

### 14.2 数据模型

| 模型 | 关键字段 |
|------|----------|
| `HypothesisResult` | factor_name, hypothesis, suggested_fields, confidence |
| `FactorSynthesisResult` | expression, input_fields, validation, warnings |
| `BacktestEvaluation` | ic_mean, sharpe, dsr, pbo, passed |
| `ReviewVerdict` | verdict (approve/reject/revise), reasoning, reviewer_model, consensus |
| `CuratorDecision` | action (accept/defer/reject), reason, risk_flags |

### 14.3 目标流程

```
KnowledgeBase + PDF Report
       ↓
  HypothesisAgent (多方向发散)
       ↓
  FactorAgent (白名单约束)
       ↓
  BacktestAgent (回测+反过拟合)
       ↓
  ReviewAgent (双模型交叉验证)
       ↓ consensus
  CuratorAgent (入库决策)
       ↓
  FactorLibraryEntry
```

---

## 15. 配置参考

### 15.1 Settings 完整字段 (settings.py)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm_provider` | `Literal["openai","anthropic"]` | `"anthropic"` | LLM 提供商 |
| `llm_api_key` | `SecretStr` | `""` | API Key |
| `llm_base_url` | `str\|None` | `None` | 自定义 API 地址 |
| `llm_model` | `str` | `"claude-sonnet-4-5"` | 文本模型 |
| `llm_vision_model` | `str` | `"claude-sonnet-4-5"` | 视觉模型 |
| `llm_temperature` | `float` | `0.0` | 生成温度 |
| `llm_seed` | `int` | `42` | 随机种子 |
| `parser_backend` | `Literal[...]` | `"finpdfpro"` | PDF 解析后端 |
| `parser_version` | `str` | `"1.0.0"` | 解析器版本 (缓存 key) |
| `finpdfpro_mode` | `Literal["fast","balanced","max-quality"]` | `"balanced"` | 解析模式 |
| `finpdfpro_vlm_backend` | `Literal[...]` | `"none"` | VLM 后端 |
| `data_source` | `Literal["ricequant","qlib","local","tushare"]` | `"local"` | 数据源 |
| `ricequant_token` | `SecretStr` | — | 米筐 Token |
| `tushare_token` | `SecretStr` | — | Tushare Token |
| `qlib_data_path` | `str\|None` | — | Qlib 数据路径 |
| `local_data_path` | `Path\|None` | — | 本地数据目录 |
| `data_dir` | `Path` | `~/.reproagent` | 数据存储根目录 |
| `max_reflection_iterations` | `int` | `3` | 反思循环上限 |
| `default_engine` | `Literal["polars","rqalpha"]` | `"polars"` | 默认因子引擎 |
| `app_env` | `Literal["dev","prod"]` | `"dev"` | 环境模式 |
| `allow_mock_llm` | `bool\|None` | `None` | 显式覆盖 mock 许可 |
| `allow_formula_fallback` | `bool\|None` | `None` | 显式覆盖公式回退 |
| `tui_theme` | `str` | `"dark"` | TUI 主题 |

**环境门控逻辑**:
- `is_prod` = `app_env == "prod"`
- `mock_llm_allowed` = `allow_mock_llm` (如果显式设置) else `not is_prod`
- `formula_fallback_allowed` = `allow_formula_fallback` (如果显式设置) else `not is_prod`

### 15.2 派生路径

| 属性 | 路径 |
|------|------|
| `db_path` | `~/.reproagent/reproagent.db` |
| `cache_dir` | `~/.reproagent/cache/` |
| `reports_dir` | `~/.reproagent/reports/` |
| `factors_dir` | `~/.reproagent/factors/` |
| `wiki_dir` | `~/.reproagent/wiki/` |
| `logs_dir` | `~/.reproagent/logs/` |

### 15.3 finreportparser 配置 (configs/)

三档 YAML 配置: `default.yaml` (balanced), `fast.yaml`, `max_quality.yaml`。

| 参数 | default | fast | max_quality |
|------|---------|------|-------------|
| `mode` | balanced | fast | max-quality |
| `workers` | 2 | 2 | 2 |
| `table_backend` | paddle | paddle | mineru |
| `vlm_backend` | paddle_vl | none | paddle_vl |
| `image_max_edge` | 768 | 512 | 768 |
| `resume` | true | true | true |
| `cpu_threads` | 4 | 4 | 4 |

### 15.4 数据守卫配置 (DataGuardConfig)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `filter_st` | True | 剔除 ST/*ST |
| `filter_suspended` | True | 剔除停牌 |
| `min_listing_days` | 60 | 最小上市天数 |
| `filter_limit_up_down` | True | 剔除涨跌停 |
| `limit_up_threshold` | 0.098 | 涨停阈值 |
| `limit_down_threshold` | -0.098 | 跌停阈值 |
| `require_forward_adjusted` | True | 要求后复权 |
| `adjustment_field` | "adj_factor" | 复权因子列名 |

---

## 16. 测试体系

### 16.1 测试结构

```
tests/
├── conftest.py                  # sample_report_path, prices_parquet_path
├── unit/                        # 19 文件，全离线，无外部依赖
│   ├── test_lookahead_detector  # 24 测试: 6 规则 + 风险等级 + 错误处理
│   ├── test_data_guards         # 19 测试: ST/停牌/新股/涨跌停/复权
│   ├── test_metrics             # 12 测试: Sharpe/MDD/IC/分组收益
│   ├── test_deviation_analyzer  # 10 测试: 偏差对比/根因/状态机
│   ├── test_llm_extractor       # 5 测试: Mock 回退路径
│   ├── test_models              # 8 测试: 模型往返/哈希/版本
│   ├── test_pdf_utils           # 9 测试: PDF 检查
│   ├── test_schema_validator    # 8 测试: WARN 标记/批量
│   ├── test_strict_mode         # 5 测试: prod 硬性失败
│   ├── test_library_filter      # 1 测试: 过滤
│   ├── test_review_queue        # 1 测试: 复核生命周期
│   ├── test_fixtures            # 2 测试: 文件存在
│   ├── test_chart_classify      # 6 测试: VLM 分类
│   ├── test_headers_footers     # 6 测试: 页眉页脚
│   ├── test_table_repair        # 6 测试: GFM 表修复
│   ├── test_text_tables         # 2 测试: 真实 PDF 文本表(条件 skip)
│   ├── test_profiles            # 5 测试: 配置预设
│   └── test_lite_e2e            # 1 测试: 真实 PDF parse_pdf(条件 skip)
├── integration/
│   └── test_e2e.py              # 4 测试: 全链路 mock
└── conformance/
    ├── test_engine_correctness  # 20 测试: 10 因子 × 2 (值比对+NaN)
    ├── test_engine_parity       # 3 测试: 确定性验证
    └── test_benchmark           # 9 测试: Schema(5) + 提取(1) + 复现(3)
```

**总计: 166 测试, ~3.5s**

### 16.2 关键 Fixtures

| Fixture | 来源 | 内容 |
|---------|------|------|
| `sample_report_path` | `conftest.py` | 1.8 KB 合成 PDF |
| `prices_parquet_path` | `conftest.py` | 60 行量价 Parquet |
| `prices_df` | `test_engine_correctness.py` | 2 资产 × 30 日 OHLCV |
| `offline_settings` | `test_e2e.py` / `test_benchmark.py` | 全线下 Settings |
| `engine` | `test_engine_correctness.py` | PolarsEngine 裸实例 |

### 16.3 运行

```bash
make test                    # uv run pytest -q
make lint                    # uv run ruff check src tests
make typecheck               # uv run mypy src/reproagent

# CI 等效
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
```

### 16.4 CI (GitHub Actions)

单 job `test` on ubuntu-latest:
1. checkout → setup-uv → uv sync --extra dev
2. ruff check → mypy → pytest -q (OPENAI_API_KEY="" ANTHROPIC_API_KEY="")

对 main/master push 和所有 PR 触发。

---

## 附录 A: 异常层级

```
ReproAgentError
├── ValidationError          # PDF / 输入校验
├── SchemaValidationError    # LLM schema 校验失败
├── ParseError               # 研报解析失败
│   └── LLMError             # LLM 提取/修订失败
├── ReproductionError        # 因子计算/回测失败
│   └── FormulaError         # 公式解析/求值失败
├── DeviationError           # 偏差分析/反思循环失败
├── LibraryError             # 因子库操作失败
├── CacheError               # 缓存读写失败
├── PersistenceError         # DB/文件系统持久化失败
└── ConfigurationError       # 配置缺失/非法
```

## 附录 B: 依赖关系图 (模块级)

```
                        ┌──────────┐
                        │  models  │ (leaf)
                        └────┬─────┘
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ settings │  │exceptions│  │  utils   │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             ↓              ↓              ↓
    ┌──────────────────────────────────────────┐
    │              persistence                  │
    └──────────────────────────────────────────┘
             ↓              ↓              ↓
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │ ingestion  │  │  parser    │  │  cache     │
    └────────────┘  └─────┬──────┘  └────────────┘
                          ↓
    ┌──────────────────────────────────────────┐
    │              reproducer                   │
    │  (polars_engine, backtester, metrics,    │
    │   anti_overfitting, data_loader,         │
    │   data_guards, lookahead_detector,       │
    │   safe_eval, rqalpha_engine)             │
    └────────────────────┬─────────────────────┘
                         ↓
    ┌──────────────────────────────────────────┐
    │              deviation                    │
    │  (imports parser.llm_extractor,          │
    │         parser.config_builder,            │
    │         parser.prompts)                   │
    └────────────────────┬─────────────────────┘
                         ↓
    ┌──────────────────────────────────────────┐
    │              library                      │
    └────────────────────┬─────────────────────┘
                         ↓
    ┌──────────────────────────────────────────┐
    │  pipeline.py (central orchestrator)       │
    └────────────────────┬─────────────────────┘
                         ↓
    ┌──────────────────────────────────────────┐
    │  cli.py / tui/ / mcp_server.py            │
    └──────────────────────────────────────────┘
```

## 附录 C: 与 aiminer 的算子对比

| ReproAgent | aiminer | 说明 |
|-----------|---------|------|
| ✅ Rank | Rank | 截面排名 |
| ✅ CSRank | CSRank | 同上 |
| ✅ CSZScore | CSZScore | 截面 z-score |
| ✅ GroupNeutral | GroupNeutral | 截面减均值 |
| ✅ Winsorize | Winsorize | 分位数 clip |
| ✅ Percentile | Percentile | 截面百分位 |
| ✅ Scale | Scale | 缩放到 sum=1 |
| ✅ Mean/Std/Sum | Mean/Std/Sum | 滚动 |
| ✅ Median | Median | 滚动中位数 |
| ✅ EMA/WMA | EMA/WMA | 指数/加权移动平均 |
| ✅ Var/Skew/Kurt | Var/Skew/Kurt | 高阶矩 |
| ✅ Mad | Mad | 中位绝对偏差 |
| ✅ Ts_Rank | Ts_Rank | 时序排名 |
| ✅ Ts_Max/Min | Ts_Max/Min | 滚动极值 |
| ✅ Ts_ArgMax/Min | Ts_ArgMax/Min | 极值位置 |
| ✅ Ts_Percentile | Ts_Percentile | 滚动百分位 |
| ✅ Count | Count | 非空计数 |
| ✅ Corr/Cov | Corr/Cov | 滚动相关 |
| ✅ Exp/Pow/Neg/Inv | Exp/Pow/Neg/Inv | 数学 |
| ✅ Ceil/Floor | Ceil/Floor | 取整 |
| ✅ If/Greater/Less/... | If/Greater/Less/... | 逻辑 |
| ✅ And/Or/Not/Clip | And/Or/Not/Clip | 布尔/截断 |
| ✅ Add/Sub/Mul/Div 别名 | Plus/Minus/Multiply/Divide/... | 算术别名 |
| ❌ Sin/Cos/Tan | Sin/Cos/Tan | 三角函数 (未实现) |
| ❌ Round | Round | 取整 (未实现) |
| ❌ Rust compiler | compile_alpha | Rust 编译器 (reproagent 纯 Python) |

覆盖率: 55/58 = 94.8%。仅缺 Sin/Cos/Tan/Round (低频使用)。

---

*全文完。总计 16 章 + 3 附录，覆盖 architecturediagrams, data models, pipeline algorithms, 
operator signatures, statistical tests, data guard rules, root cause classification, 
experience memory, factor library, CLI/TUI/MCP interfaces, multi-agent design, 
configuration reference, test infrastructure, exception hierarchy, module dependencies, 
and aiminer operator comparison.*
