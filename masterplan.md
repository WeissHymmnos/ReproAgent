# ReproAgent — Master Plan

> 研报因子自动复现系统。上传 PDF 卖方研报 → 解析因子定义 → 回测复现 → 偏差自愈 → 入因子库。
>
> 本文档是面向 coding agent 的施工蓝图:每个文件、每个类、每个方法都有具体实现建议。
> 参考 flowchart 中的 6 个子系统,逐一给出文件级实现方案。

---

## 0. 项目总览

### 定位

单用户 CLI/TUI 应用,用于将中国 A 股卖方研报(中信、国泰君安、华泰等)中的量化因子从 PDF 中提取并自动复现,偏差在容忍区间内则入库,否则进入有限反思循环,最多 N=3 次自愈,仍不收敛则进人工复核队列。

### 技术栈决策一览

| 层 | 技术选型 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ | 生态齐全(ML/quant/LLM) |
| 包管理 | `uv` + `pyproject.toml` (PEP 621) | 速度远快于 pip/poetry |
| 数据模型 | Pydantic v2 `BaseModel` | 跨 LLM/YAML/DB 三界序列化 |
| 持久化-元数据 | SQLite via SQLModel | 单用户、关系查询、Pydantic v2 兼容 |
| 持久化-大数据 | Parquet 文件 (Polars 原生) | 因子值、净值曲线宽表 |
| 因子计算主引擎 | Polars (lazy API) | 10-100x pandas、`over()` 面板感知 |
| 回测引擎 | rqalpha (v6.1.4,活跃维护) | 中文 A 股日频回测、免费数据 |
| PDF 布局提取 | Marker (`marker-pdf`) + MinerU(备选) | 自托管、GPU 高吞吐、高保真 Markdown |
| PDF 表格(CN 金融表) | MinerU 或 LlamaParse(agentic tier) | 跨页表格、无框线表格最佳 |
| LLM 结构化提取 | OpenAI Structured Outputs / Anthropic tool-use + Pydantic schema | JSON 严格模式、可验证 |
| CLI | Typer | 类型提示原生、Rich 集成 |
| TUI | Textual (async) | 现代终端 UI、CSS 主题、命令面板 |
| 配置 | `pydantic-settings` + `.env` | 类型安全、嵌套支持 |
| 日志 | loguru | 结构化、文件轮转零配置 |
| 模板 | Jinja2 | LLM prompt 模板化 |
| 测试 | pytest + `tests/conformance/` 引擎一致性 | 引擎间偏差回归 |

### 参考架构(必读)

| 项目 | URL | 参考价值 |
|---|---|---|
| **zer0factor** | github.com/zer0quant/zer0factor | 最近邻:研报→FactorSpec→compute()→Parquet 全流程,MIT,活跃维护(2026-07)。miror `FactorSpec + FactorFrame + compute()` 接口设计 |
| **AgentQuant** | github.com/OnePunchMonk/AgentQuant | 反思循环范式:`analyze→hypothesize→backtest→reflect`。reflect 节点检查 `sharpe >= min_acceptable_sharpe`,不满足则 retry。bounded loop + SQLite memory。读 `src/agent/agent_graph.py` 和 `src/agent/proposal_generator.py` |
| **qlib + KunQuant** | github.com/microsoft/qlib (44K★) | Alpha158 因子表达式语法标准;KunQuant 的 `test against alpha158.npz reference` 模式即"计算值 vs 参考值"一致性校验 |
| **alpha-lens** | github.com/ellatso/alpha-lens | Production Readiness Score:DSR + PBO + MinBTL + walk-forward + bootstrap Sharpe CI。直接复用其偏差门控逻辑 |
| **QuantsPlaybook** | github.com/hugo2046/QuantsPlaybook | 100+ 券商金工研报复现,光大/华泰/招商/国信。理解"忠实复现"的 CN 业界标准(注意:2023 后 dormat) |

---

## 1. 目录结构

```
reproagent/
├── pyproject.toml                     # uv + PEP 621
├── uv.lock
├── README.md
├── masterplan.md                      # 本文档
├── .env.example                       # 配置模板
├── Makefile                           # 常用命令别名
│
├── src/reproagent/
│   ├── __init__.py                    # 版本号 __version__
│   ├── __main__.py                    # `python -m reproagent` 入口
│   ├── cli.py                         # Typer CLI: ingest / reproduce / library / review / tui
│   ├── settings.py                    # pydantic-settings Settings 单例
│   ├── logging_setup.py              # loguru 配置 + 文件轮转
│   ├── exceptions.py                 # 异常层级:ReproAgentError → 子类
│   │
│   ├── models/                       # Pydantic v2 纯领域模型(无 DB 耦合)
│   │   ├── __init__.py
│   │   ├── report.py                 # ResearchReport, ReportedMetrics
│   │   ├── factor_spec.py            # ParsedFactorSpec, FactorInputField, DataDictMapping
│   │   ├── factor_def.py             # FactorDefinition(规范化后的因子定义)
│   │   ├── replication.py            # ReplicationConfig, BacktestParams
│   │   ├── backtest.py               # BacktestResult
│   │   ├── comparison.py             # ComparisonReport
│   │   ├── deviation.py              # DeviationReport, ToleranceConfig, RootCause
│   │   ├── reflection.py             # ReflectionState, ReflectionStep
│   │   └── library.py                # FactorLibraryEntry, LibraryFilter
│   │
│   ├── ingestion/                    # 子系统 1:研报摄入与预处理
│   │   ├── __init__.py
│   │   ├── uploader.py               # upload_pdf(path) → ResearchReport
│   │   ├── validator.py              # validate_pdf(pdf):格式/页数/可读性
│   │   └── review_queue.py           # 人工复核队列入队/出队
│   │
│   ├── parser/                       # 子系统 2:研报解析层 ReportParser
│   │   ├── __init__.py
│   │   ├── protocol.py               # ReportParserProtocol
│   │   ├── layout_extractor.py       # Marker/LlamaParse/MinerU → Markdown
│   │   ├── llm_extractor.py          # Vision LLM + Pydantic schema → ParsedFactorSpec[]
│   │   ├── schema_validator.py       # 校验 + 数据字典映射 [OK]/[WARN] 标注
│   │   ├── config_builder.py         # ParsedFactorSpec[] → ReplicationConfig → 导出 config.yaml
│   │   └── prompts.py                # Jinja2 提取/反思提示模板
│   │
│   ├── reproducer/                   # 子系统 3:因子复现层 FactorReproducer
│   │   ├── __init__.py
│   │   ├── protocol.py               # FactorReproducerProtocol, FactorEngine Protocol
│   │   ├── reproducer.py             # FactorReproducer 编排器
│   │   ├── evaluator_factory.py      # build_evaluator(config) → FactorEngine
│   │   ├── polars_engine.py          # PolarsEngine:Polars 因子计算
│   │   ├── rqalpha_engine.py         # RiceQuantEval:rqalpha 因子计算
│   │   ├── backtester.py             # StrategyBacktester:分组回测 + IC
│   │   ├── data_loader.py            # 数据加载:ricequant/tushare/local → pl.DataFrame
│   │   └── metrics.py                 # 指标提取 + 图表生成
│   │
│   ├── deviation/                    # 子系统 4:偏差控制与自愈
│   │   ├── __init__.py
│   │   ├── protocol.py               # DeviationAnalyzerProtocol
│   │   ├── analyzer.py               # DeviationAnalyzer:对比 + 容忍检查
│   │   ├── tolerances.py             # ToleranceConfig 默认容忍区间(业界标准)
│   │   ├── root_cause.py              # classify_root_cause() → RootCause 枚举
│   │   └── reflection_loop.py        # ReflectionLoopController:N≤3、持久化、防震荡
│   │
│   ├── library/                      # 子系统 5:因子库管理层
│   │   ├── __init__.py
│   │   ├── protocol.py               # FactorLibraryProtocol
│   │   ├── manager.py                # FactorLibraryManager:register/get/list
│   │   ├── versioning.py             # semver bump + dedup_hash 计算
│   │   ├── classifier.py             # 风格自动分类:规则优先 + LLM fallback
│   │   ├── index_writer.py           # 重生成全局 INDEX.md
│   │   └── wiki_writer.py            # 生成逐因子 Markdown wiki 页
│   │
│   ├── persistence/                  # 存储层(SQLModel + 文件系统)
│   │   ├── __init__.py
│   │   ├── db.py                     # engine/session 工厂(SQLite via SQLModel)
│   │   ├── tables.py                 # SQLModel 表类(映射 ↔ 领域模型)
│   │   ├── repository.py             # 通用 CRUD:save/load 领域模型
│   │   └── paths.py                  # AppPaths:所有文件系统路径约定
│   │
│   ├── cache/                        # 缓存层
│   │   ├── __init__.py
│   │   ├── cache_manager.py          # CacheManager:key 计算、命中/未命中
│   │   └── cache_key.py              # hash(pdf) + parser_version + model_version
│   │
│   ├── tui/                          # 子系统 6:前端展示
│   │   ├── __init__.py
│   │   ├── app.py                    # ReproAgentApp(Textual App)
│   │   ├── commands.py               # 命令面板定义
│   │   ├── screens/
│   │   │   ├── __init__.py
│   │   │   ├── reproduction.py       # 研报复现页
│   │   │   ├── library_browser.py    # 因子库浏览器
│   │   │   └── review.py            # 人工复核页面
│   │   └── widgets/
│   │       ├── __init__.py
│   │       ├── factor_tree.py        # 因子库树视图
│   │       ├── deviation_gauge.py    # 偏差可视化仪表
│   │       └── log_panel.py          # 流式 loguru 输出
│   │
│   └── utils/
│       ├── __init__.py
│       ├── hashing.py                # sha256_file(), content_hash()
│       ├── pdf.py                    # 页数、可读性检查(pypdf)
│       └── plotting.py              # matplotlib 图表 → PNG/HTML
│
└── tests/
    ├── conftest.py
    ├── conformance/                   # Polars vs rqalpha 引擎一致性测试
    │   └── test_engine_parity.py
    ├── fixtures/
    │   └── sample_reports/           # 样例研报 PDF
    └── ...
```

### 为什么用 `src/` 布局

`src/` 布局防止从 repo 根目录意外 `import reproagent`(未安装即导入,掩盖打包错误)。强制 `pip install -e .` 后才能 import,及早暴露缺失依赖和 `__init__.py` 问题。对要发布和测试的项目,不可妥协。

---

## 2. 领域模型(Pydantic v2)

> 全部跨 LLM 边界(需 `model_json_schema()`)、YAML 边界(需序列化)、DB 边界(需 from 行映射)。用 dataclass 会需要一个额外的序列化层,不值得。统一 Pydantic v2 `BaseModel`。

### 2.1 `models/report.py`

```python
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from pydantic import BaseModel


class ResearchReport(BaseModel):
    """摄入的一篇研报。"""
    id: str                              # UUID4
    file_path: Path                      # 原始 PDF 位置
    file_hash: str                       # PDF 字节 SHA256
    title: str | None = None
    author: str | None = None
    broker: str | None = None            # 如 "中信证券", "国泰君安"
    report_date: date | None = None
    page_count: int
    validation_status: Literal["pending", "valid", "invalid"] = "pending"
    validation_errors: list[str] = []
    ingested_at: datetime                # UTC


class ReportedMetrics(BaseModel):
    """研报中声称的指标(LLM 从表格/正文提取)。"""
    ic_mean: float | None = None
    ic_ir: float | None = None
    long_short_return: float | None = None      # 年化,%
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    group_monotonicity: bool | None = None       # 顶-底分组排序是否单调
    source_pages: list[int] = []                # 在 PDF 哪些页找到
```

### 2.2 `models/factor_spec.py`

```python
class FactorInputField(BaseModel):
    """因子的一个输入字段。"""
    name: str                            # 映射后规范化名,如 "turnover_rate"
    report_name: str                     # 研报原文术语,如 "换手率"
    data_type: Literal["price", "volume", "fundamental", "macro", "derived"]
    description: str = ""
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "annual"] = "daily"


class DataDictMapping(BaseModel):
    """研报术语 → 规范化数据字典映射。"""
    report_term: str                     # 如 "换手率"
    canonical_term: str                  # 如 "turnover_rate"
    confidence: float                    # 0.0–1.0
    tag: Literal["OK", "WARN"]           # confidence ≥ 0.8 → OK,否则 WARN
    note: str | None = None


class ParsedFactorSpec(BaseModel):
    """LLM 从研报中提取的一个因子的原始结构化定义。"""
    id: str                              # UUID4
    factor_name: str                     # 英文/规范化名
    factor_name_cn: str                  # 研报中文原名
    description: str
    formula: str                         # LaTeX 或结构化伪代码
    input_fields: list[FactorInputField]
    computation_steps: list[str]         # 有序、人类可读的计算步骤
    rebalance_frequency: Literal["daily", "weekly", "monthly", "quarterly"] = "monthly"
    universe: str = "全A股"              # 股票池描述
    lookback_window: int | None = None
    data_dict_mappings: list[DataDictMapping] = []
    extraction_confidence: float         # 0.0–1.0,来自 LLM
    source_pages: list[int] = []         # 因子在 PDF 哪些页描述
    reported_metrics: ReportedMetrics | None = None
```

### 2.3 `models/factor_def.py`

```python
class FactorDefinition(BaseModel):
    """规范化、可计算的因子定义。"""
    id: str
    spec_id: str                         # FK → ParsedFactorSpec.id
    name: str
    name_cn: str
    style: Literal["value", "growth", "momentum", "quality", "size",
                   "volatility", "liquidity", "macro", "technical", "other"]
    formula: str
    input_fields: list[str]              # 仅规范化名
    computation_code: str | None = None  # 生成的 Polars 表达式字符串
    universe: str
    rebalance_frequency: str
    version: str = "0.1.0"              # semver
```

### 2.4 `models/replication.py`

```python
class BacktestParams(BaseModel):
    """回测参数。"""
    start_date: date
    end_date: date
    initial_capital: float = 1_000_000.0
    benchmark: str = "000300.SH"         # 沪深 300
    rebalance_frequency: Literal["daily", "weekly", "monthly", "quarterly"] = "monthly"
    num_groups: int = 5                  # 五分组
    transaction_cost_bps: float = 3.0    # 每次换手 basis points


class ReplicationConfig(BaseModel):
    """一次复现的完整配置,导出为 config.yaml。"""
    id: str
    report_id: str                       # FK → ResearchReport.id
    factor_specs: list[ParsedFactorSpec]
    engine: Literal["polars", "rqalpha"] = "polars"
    data_source: Literal["ricequant", "tushare", "local"] = "ricequant"
    backtest_params: BacktestParams
    parser_version: str                  # 如 "marker-1.0.0" — 缓存失效用
    extraction_model_id: str             # 如 "claude-sonnet-4-5" — 缓存 key 用
    config_version: str = "1.0"          # 配置 schema 版本
    created_at: datetime
```

### 2.5 `models/backtest.py`

```python
class BacktestResult(BaseModel):
    """一次回测的完整结果。"""
    id: str
    config_id: str                       # FK → ReplicationConfig.id
    factor_id: str                        # FK → FactorDefinition.id
    engine: str
    start_date: date
    end_date: date
    # 核心指标
    group_annualized_returns: dict[int, float]   # {1: 0.12, 2: 0.08, ...}
    ic_mean: float
    ic_ir: float                          # IC 信息比
    long_short_annual_return: float       # group_N - group_1, 年化
    sharpe_ratio: float
    max_drawdown: float
    turnover: float
    # 大数据文件系统指针
    factor_values_path: Path              # parquet: date, asset, factor_value
    equity_curve_path: Path               # parquet: date, group_1..N, long_short
    computed_at: datetime
```

### 2.6 `models/comparison.py`

```python
class ComparisonReport(BaseModel):
    """复现值 vs 研报声称值的对比报告。"""
    id: str
    factor_id: str
    reproduced: BacktestResult
    reported: ReportedMetrics
    metric_deltas: dict[str, float]       # {"ic_mean": 0.03, "sharpe": 0.5, ...}
                                          # 复现值 - 研报值
```

### 2.7 `models/deviation.py`

```python
from enum import Enum


class RootCause(str, Enum):
    """偏差根因分类。"""
    DATA_MISMATCH = "data_mismatch"       # 数据源/字段映射错误
    FORMULA_ERROR = "formula_error"       # LLM 读错公式
    PARAMETER_ERROR = "parameter_error"   # 窗口、频率、股票池参数错误
    UNIVERSE_MISMATCH = "universe_mismatch"
    LOOKAHEAD_BIAS = "lookahead_bias"      # 未来函数
    UNKNOWN = "unknown"


class ToleranceConfig(BaseModel):
    """核心指标容忍区间(业界标准,见 §4.2)。"""
    ic_mean_abs: float = 0.03             # |ΔIC| ≤ 0.03
    ic_ir_abs: float = 0.2
    long_short_return_rel: float = 0.15   # 15% 相对偏差
    sharpe_abs: float = 0.3
    max_drawdown_abs: float = 0.05


class DeviationReport(BaseModel):
    """偏差分析结果。"""
    id: str
    comparison_id: str
    factor_id: str
    passed: bool
    metric_deviations: dict[str, float]    # 指标 → 偏差大小
    tolerances: ToleranceConfig
    root_cause: RootCause = RootCause.UNKNOWN
    root_cause_detail: str = ""
    recommend_reflect: bool = False
    reflection_state_id: str | None = None
```

### 2.8 `models/reflection.py`

```python
class ReflectionStep(BaseModel):
    """反思循环中的一次迭代。"""
    id: str
    state_id: str                         # FK → ReflectionState.id
    iteration: int                        # 0-indexed
    prompt: str                           # 发给 LLM 的完整 prompt
    response: str                         # LLM 原始响应
    revised_config: ReplicationConfig
    deviation_report: DeviationReport | None = None
    created_at: datetime


class ReflectionState(BaseModel):
    """反思循环的完整状态,持久化以支持崩溃恢复。"""
    id: str
    factor_id: str
    report_id: str
    original_config: ReplicationConfig
    max_iterations: int = 3
    current_iteration: int = 0
    status: Literal["in_progress", "converged", "exhausted", "escalated"] = "in_progress"
    steps: list[ReflectionStep] = []
    best_deviation_score: float | None = None   # 所有迭代中最小偏差
    best_step_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

### 2.9 `models/library.py`

```python
class FactorLibraryEntry(BaseModel):
    """因子库中的一条记录。"""
    id: str
    factor: FactorDefinition
    report_id: str
    config_id: str
    backtest_result_id: str
    deviation_passed: bool
    status: Literal["ready", "review", "deprecated"] = "ready"
    version: str                          # semver,如 "1.0.0"
    dedup_hash: str                       # sha256(formula + sorted(input_fields))
    tags: list[str] = []
    created_at: datetime


class LibraryFilter(BaseModel):
    """因子库过滤条件。"""
    style: str | None = None
    status: str | None = None
    broker: str | None = None
    tags: list[str] = []
```

---

## 3. 子系统逐层实现方案

### 子系统 1:研报摄入与预处理 `ingestion/`

#### 文件级实现

**`ingestion/uploader.py`**

```python
def upload_pdf(file_path: Path) -> ResearchReport:
    """上传一篇 PDF → 创建 ResearchReport 对象(file_hash + page_count 即时计算)。
    单篇支持;批量简单地 for 循环调用此函数即可。"""
```

- 用 `utils/hashing.py::sha256_file(path)` 计算 `file_hash`
- 用 `utils/pdf.py::get_page_count(path)` (pypdf) 获取 `page_count`
- `id` = `uuid4().hex`
- `ingested_at` = `datetime.utcnow()`
- `title`/`author`/`broker`/`report_date` 初始为 None,后续由 parser 填充

**`ingestion/validator.py`**

```python
def validate_pdf(report: ResearchReport) -> ResearchReport:
    """PDF 合法性校验:格式/页数/可读性。
    失败 → validation_status="invalid" + validation_errors 填充。
    成功 → validation_status="valid"。"""

# 校验项:
# 1. 格式:文件头是否 %PDF,扩展名 .pdf
# 2. 页数:1 ≤ page_count ≤ 200(卖方研报通常 5-50 页;极度异常则标记 invalid)
# 3. 可读性:pypdf 能解析首页文本且非全空(scanned PDF 也 OK,有图片即算可读)
```

- 参考工具:`pypdf.PdfReader` 检测页数和文本提取
- 极端值策略:页数 > 200 → `validation_errors.append("页数异常:超过200页")`,但仍标记为 valid(告警不阻断)

**`ingestion/review_queue.py`**

```python
def enqueue_manual_review(report: ResearchReport, reason: str) -> str:
    """将报告加入人工复核队列,返回 queue_entry_id。"""

def dequeue_manual_review() -> tuple[str, ResearchReport, str] | None:
    """取出队首项:(entry_id, report, reason)。"""

def confirm_manual_review(entry_id: str, decision: Literal["approve", "reject"]) -> None:
    """人工确认后,approve → 进入 RegisterReady 流程;reject → 终止。"""
```

- 队列存储:SQLite 表 `manual_review_queue(id, report_id, reason, status, created_at)`
- 流程图语义:`Error → 人工介入` 和 `humanReviewQueue → 人工确认 → RegisterReady` 统一由本文件管理

---

### 子系统 2:研报解析层 `parser/`

#### Protocol

**`parser/protocol.py`**

```python
from typing import Protocol


class ReportParserProtocol(Protocol):
    def parse(self, report: ResearchReport) -> list[ParsedFactorSpec]:
        """全流程:布局提取 → LLM 结构化提取 → schema 校验。
        每篇研报一个因子返回一个 spec。
        校验失败重试 1 次后仍失败 → 抛 SchemaValidationError。"""
        ...

    def build_config(
        self, specs: list[ParsedFactorSpec], report: ResearchReport
    ) -> ReplicationConfig:
        """将 specs + 回测参数组装为 ReplicationConfig。
        副作用:导出 config.yaml 到文件系统。"""
        ...
```

#### 布局提取 `parser/layout_extractor.py`

> 从 PDF 提取高保真 Markdown,供 LLM 提取用。

```python
class LayoutExtractor:
    def __init__(self, backend: Literal["marker", "llamaparse", "mineru"] = "marker"):
        self.backend = backend

    def extract(self, report: ResearchReport) -> str:
        """返回完整 Markdown 文本。"""
```

**实现选项(按推荐度排序):**

**选项 A:Marker(自托管,GPU 推荐)**

```python
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict

_artifact_dict = create_model_dict()  # 模块级单例,加载一次
_converter = PdfConverter(_artifact_dict)

def extract_with_marker(pdf_path: Path) -> str:
    output = _converter(str(pdf_path))
    return output.markdown
```

- 安装:`pip install marker-pdf`
- 基准:opendataloader-bench 得分 0.861,H100 上 ~122 页/秒
- CPU fallback 慢 10-50x,生产环境强烈建议 GPU
- 表格提取:有框线表格准确;无框线/合并单元格不一致
- `--use_llm` 模式提升表格准确度但增加延迟
- **数据不离开本地** vs LlamaParse

**选项 B:MinerU(CN 金融表最佳)**

```python
# MinerU 在 CN 金融研报表格上表现最好,尤其跨页表格
# 参考 github.com/OpenDataLab/MinerU
# API:命令行 `magic-pdf` 或 Python SDK
# 适用于无框线表格、复杂版面的中文研报
```

- 2026 基准:CN 金融表准确率生产级,比 GPT-4o 原生方案便宜 7x
- 跨页表格是其强项

**选项 C:LlamaParse(托管 API,agentic tier)**

```python
from llama_cloud import LlamaCloud

_client = LlamaCloud()  # 读取 LLAMA_CLOUD_API_KEY 环境变量

def extract_with_llamaparse(pdf_path: Path) -> str:
    file = _client.files.create(file=str(pdf_path), purpose="parse")
    result = _client.parsing.parse(
        file_id=file.id, tier="agentic", version="latest",
        expand=["markdown"]
    )
    return result.markdown.pages[0].markdown  # 拼接所有页
```

- 安装:`pip install llama-parse`
- Tier 选择:测试用 `cost-effective`(3 credits/页),生产用 `agentic`(10 credits/页)
- 无框线表格准确度 最佳
- **注意:数据上传到云端**;敏感研报慎用
- 多栏布局可能交错相邻栏文本 — Marker 更强

**建议策略:** 默认 Marker 本地;遇到 Marker 弱的跨页表格降级到 MinerU;仅在本地无 GPU 且可接受云端时用 LlamaParse。

#### LLM 结构化提取 `parser/llm_extractor.py`

> Vision 模型 + Pydantic schema 从 Markdown/图片中提取因子定义。

```python
class LLMExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, report: ResearchReport, markdown: str) -> list[ParsedFactorSpec]:
        """将研报 Markdown 发给 Vision LLM,用 Pydantic schema 约束输出。
        返回所有识别到的因子。"""

    def revise(self, prompt: str, original_spec: ParsedFactorSpec) -> ParsedFactorSpec:
        """反思循环中,给定偏差历史,prompt LLM 生成修订版 spec。"""
```

**核心实现(OpenAI Structured Outputs 模式):**

```python
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator, model_validator

# 定义提取 schema(结构化输出)
class FactorExtractionEnvelope(BaseModel):
    """LLM 输出的完整信封:包含一篇研报中所有因子。"""
    factors: list[ParsedFactorSpec] = Field(description="研报中识别到的所有因子")
    report_title: str | None = None
    broker: str | None = None
    report_date: str | None = None
    extraction_confidence: float = Field(description="整体提取置信度 0-1")

client = OpenAI()

# PDF 页转 base64 图片(可选,用于 Vision 模式)
import base64
from pdf2image import convert_from_path

def pdf_pages_to_base64(pdf_path: Path) -> list[str]:
    images = convert_from_path(str(pdf_path), dpi=200)
    encoded = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded.append(base64.b64encode(buf.getvalue()).decode())
    return encoded

# 结构化提取(vision + markdown 组合)
def extract_with_vision(markdown: str, page_images: list[str]) -> FactorExtractionEnvelope:
    response = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",  # structured outputs 需此版本或更新
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": f"研报 Markdown:\n{markdown}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_images[0]}"}}
            ]}
        ],
        response_format=FactorExtractionEnvelope,
        temperature=0.0,
    )
    return response.choices[0].message.parsed

EXTRACTION_SYSTEM_PROMPT = """你是一位量化研究分析师。从中国 A 股卖方研报中提取因子定义。
对每个因子,提取:
- factor_name: 英文名/规范化名
- factor_name_cn: 研报中文原名
- formula: 数学公式(LaTeX 或结构化伪代码)
- input_fields: 输入字段列表(每个含 report_name 原文术语 + data_type)
- computation_steps: 有序计算步骤
- universe: 股票池(如"全A股"、"沪深300")
- rebalance_frequency: 调仓频率
- reported_metrics: 研报声称的 IC、IR、夏普等(如有)
- extraction_confidence: 提取置信度 0-1
- source_pages: 在 PDF 哪些页描述该因子
缺失值用 null,不要编造。"""
```

**关键要求:**
- 模型必须是 `gpt-4o-2024-08-06` 或更新版本以支持 structured outputs
- 传 **类**,不是实例:`response_format=FactorExtractionEnvelope`
- `temperature=0.0` + 固定 seed 保证可复现性
- 校验失败:重试 1 次,在 prompt 中反馈具体 schema 错误;仍失败 → 人工复核队列

**备选:用 `instructor` 库自动重试**

```python
import instructor
client = instructor.from_openai(OpenAI())
# instructor 自动在 Pydantic 校验失败时重试,并在 prompt 中注入错误信息
```

#### Schema 校验 + 数据字典映射 `parser/schema_validator.py`

```python
class SchemaValidator:
    def validate(self, spec: ParsedFactorSpec) -> ParsedFactorSpec:
        """校验并标注 [OK]/[WARN]。
        1. 公式语法校验(LaTeX 可解析、引用的变量都在 input_fields 中)
        2. 数据字典映射:为每个 input_field.report_name 查找规范化名
           - 高置信(≥0.8)→ tag="OK"
           - 低置信(<0.8)→ tag="WARN" + note 说明
        3. extraction_confidence > 0.7 → 通过;否则标记需人工复核
        """
```

- 数据字典:一个静态映射表(内置 YAML),如 `{"换手率": "turnover_rate", "市盈率": "pe_ttm", ...}`
- 低置信映射时 tag=WARN,后续 reprocer 会对 WARN 字段做更保守的处理(如降级到人工)
- `extractQualChecker` 还是 Optional:先规则匹配,不命中再调 LLM 做语义映射

#### 配置生成 `parser/config_builder.py`

```python
class ConfigBuilder:
    def build_config(
        self, specs: list[ParsedFactorSpec], report: ResearchReport
    ) -> ReplicationConfig:
        """组装 ReplicationConfig:
        - engine: 默认 "polars"(settings 可配)
        - data_source: 默认 "ricequant"
        - backtest_params: 从 settings 读取默认 + 研报提取的 date range
        - parser_version: settings.parser_version(缓存 key 用)
        - extraction_model_id: settings.llm_vision_model
        - created_at: utcnow
        副作用:导出 config.yaml 到 ~/.reproagent/reports/<report_id>/config.yaml
        """
```

- YAML 导出用 `pyyaml`: `yaml.dump(config.model_dump(), f, allow_unicode=True, sort_keys=False)`

#### 提示模板 `parser/prompts.py`

> Jinja2 模板,分离提取和反思两类 prompt。

```python
from jinja2 import Template

EXTRACTION_PROMPT = Template("""...""")  # 见 §llm_extractor

REFLECTION_PROMPT = Template("""你正在复现中国卖方研报中的量化因子。

## 原始因子定义
- 名称: {{ original_spec.factor_name }} ({{ original_spec.factor_name_cn }})
- 公式: {{ original_spec.formula }}
- 股票池: {{ original_spec.universe }}
- 调仓: {{ original_spec.rebalance_frequency }}

## 之前的复现尝试
{% for step in history %}
### 尝试 {{ loop.index }}
- 使用公式: {{ step.revised_config.factor_specs[0].formula }}
- 偏差:
  - IC 均值偏差: {{ step.deviation_report.metric_deviations.get("ic_mean", "N/A") }}
  - 多空年化收益偏差: {{ step.deviation_report.metric_deviations.get("long_short_return", "N/A") }}
  - 夏普偏差: {{ step.deviation_report.metric_deviations.get("sharpe", "N/A") }}
- 根因分类: {{ step.deviation_report.root_cause.value }}
- 详情: {{ step.deviation_report.root_cause_detail }}
{% endfor %}

## 最近一次偏差
- IC 均值偏差: {{ latest_deviation.metric_deviations.get("ic_mean") }}
- 根因: {{ latest_deviation.root_cause.value }}
- 详情: {{ latest_deviation.root_cause_detail }}

请修订因子定义以减少偏差,聚焦于识别出的根因。输出修订后的完整 ParsedFactorSpec。""")
```

---

### 子系统 3:因子复现层 `reproducer/`

#### Protocol

**`reproducer/protocol.py`**

```python
class FactorEngine(Protocol):
    """可插拔计算引擎(Polars 或 rqalpha)。"""
    def compute(
        self, factor_def: FactorDefinition, universe: str,
        start: date, end: date,
    ) -> pl.DataFrame:
        """返回 DataFrame: 列 [date, asset, factor_value],按 date, asset 排序。"""
        ...


class FactorReproducerProtocol(Protocol):
    def reproduce(self, config: ReplicationConfig) -> BacktestResult:
        """全流程:计算因子 → 回测 → 指标 → 图表。单次调用一个因子。"""
        ...

    def compute_factor(
        self, config: ReplicationConfig, spec: ParsedFactorSpec
    ) -> tuple[FactorDefinition, pl.DataFrame]:
        """返回(规范化 FactorDefinition, 因子值 DataFrame)。"""
        ...
```

#### 编排器 `reproducer/reproducer.py`

```python
class FactorReproducer:
    """实现 FactorReproducerProtocol。编排计算→回测→指标全流程。"""

    def __init__(self, settings: Settings, data_loader: DataLoader):
        self.settings = settings
        self.data_loader = data_loader

    def reproduce(self, config: ReplicationConfig) -> BacktestResult:
        spec = config.factor_specs[0]  # 单因子单次调用
        factor_def, factor_values = self.compute_factor(config, spec)
        backtest_result = self.backtester.run(factor_values, config.backtest_params, factor_def)
        return backtest_result

    def compute_factor(
        self, config: ReplicationConfig, spec: ParsedFactorSpec
    ) -> tuple[FactorDefinition, pl.DataFrame]:
        # 1. 构建 FactorDefinition
        factor_def = self._build_factor_def(spec)
        # 2. 工厂创建引擎
        engine = build_evaluator(config)
        # 3. 计算因子值
        factor_values = engine.compute(
            factor_def, spec.universe,
            config.backtest_params.start_date, config.backtest_params.end_date,
        )
        return factor_def, factor_values
```

#### 引擎工厂 `reproducer/evaluator_factory.py`

> 流程图中的 `build_evaluator()`。

```python
def build_evaluator(config: ReplicationConfig) -> FactorEngine:
    if config.engine == "polars":
        return PolarsEngine(config)
    elif config.engine == "rqalpha":
        return RiceQuantEval(config)
    else:
        raise ValueError(f"未知引擎: {config.engine}")
```

#### Polars 引擎 `reproducer/polars_engine.py`

```python
class PolarsEngine:
    """实现 FactorEngine Protocol。用 Polars lazy API 计算因子。"""

    def __init__(self, config: ReplicationConfig):
        self.config = config

    def compute(
        self, factor_def: FactorDefinition, universe: str,
        start: date, end: date,
    ) -> pl.DataFrame:
        # 1. 加载原始数据(量价、基本面)
        raw = self._load_raw_data(factor_def.input_fields, universe, start, end)
        # 2. 构建 lazy 计划
        lf = raw.lazy().sort(["trade_date", "ts_code"])
        # 3. 应用因子计算(这里展示一个动量因子示例)
        result = (
            lf.with_columns([
                pl.col("close").pct_change(20).over("ts_code").alias("momentum_20d"),
                pl.col("volume").rolling_mean(20).over("ts_code").alias("vol_ma20"),
            ])
            .select(["trade_date", "ts_code", "momentum_20d"])
            .rename({"trade_date": "date", "ts_code": "asset", "momentum_20d": "factor_value"})
            .filter(pl.col("factor_value").is_not_null())
        )
        return result.collect()
```

**Polars 关键技巧:**
- `over("ts_code")` 面板感知:按股票分组做 rolling/pct_change,无需显式 group_by
- `group_by_dynamic` 时间窗分组(需先 sort)
- `scan_parquet` lazy 加载,`collect()` 触发执行
- pandas 互转零拷贝:`df.to_pandas()` / `pl.from_pandas(pd_df)`

#### rqalpha 引擎 `reproducer/rqalpha_engine.py`

> 流程图中的 `RiceQuantEval`。注意:**RiceQuantEval 不是真实包**,用 rqalpha 直接实现。

```python
class RiceQuantEval:
    """用 rqalpha 计算因子值。实现 FactorEngine Protocol。"""

    def __init__(self, config: ReplicationConfig):
        self.config = config

    def compute(
        self, factor_def: FactorDefinition, universe: str,
        start: date, end: date,
    ) -> pl.DataFrame:
        # 用 rqalpha 的 history_bars 获取数据,在其中计算因子
        # rqalpha 主要用于回测,因子计算可退化为 polars + rqalpha 数据源
        ...
```

**rqalpha 关键 API:**
- `pip install rqalpha` (v6.1.4,活跃维护,2026-06 仍更新)
- `rqalpha download-bundle` 下载免费日频 A 股数据
- `run_func(init, handle_bar, config)` 运行回测
- `history_bars(symbol, n, frequency, field)` 获取历史 K 线
- `order_percent(symbol, percent)` 目标仓位
- Mod 系统:自定义因子 Hook,见 [rqalpha Mod Hooks](https://rqalpha.readthedocs.io/zh-cn/latest/intro/hook.html)
- 开源版只有日频 + 回测;分钟/Tick 需付费 RiceQuant 订阅

#### 回测器 `reproducer/backtester.py`

```python
class StrategyBacktester:
    """分组回测 + IC 计算。接受因子值 DataFrame,产生分组收益、IC、夏普等。"""

    def run(
        self, factor_values: pl.DataFrame, params: BacktestParams,
        factor_def: FactorDefinition,
    ) -> BacktestResult:
        # 1. 按 factor_value 分组成 N 组(quantile)
        # 2. 计算各组收益(等权 or 市值加权)
        # 3. 多空组合 = group_N - group_1
        # 4. 计算 IC(截面 rank IC,按日期)
        # 5. 计算 IC 均值 + ICIR
        # 6. 计算夏普、最大回撤、换手
        # 7. 保存 equity_curve 和 factor_values 到 parquet
        # 8. 返回 BacktestResult
```

**分组回测算法:**
```python
def quantile_grouping(factor_values: pl.DataFrame, num_groups: int = 5) -> pl.DataFrame:
    """每日截面按因子值分位分组。返回含 group 列的 DataFrame。"""
    return (
        factor_values
        .sort(["date", "factor_value"])
        .group_by("date", maintain_order=True)
        .map_groups(lambda g: g.with_columns(
            pl.lit(np.digitize(
                np.arange(len(g)),
                np.linspace(0, len(g), num_groups + 1)[:-1]
            ) + 1).alias("group")
        ))
    )
```

#### 数据加载 `reproducer/data_loader.py`

```python
class DataLoader:
    """从 ricequant/tushare/local 加载量价和基本面数据为 Polars DataFrame。"""

    def load_price_data(self, universe: str, start: date, end: date) -> pl.DataFrame:
        """加载日频量价:trade_date, ts_code, open, high, low, close, volume, amount。"""

    def load_fundamental_data(self, fields: list[str], start: date, end: date) -> pl.DataFrame:
        """加载基本面:如 roe_ttm, pe_ttm, turnover_rate。"""
```

- ricequant:用 rqalpha 的 bundle 数据
- tushare:`pip install tushare`,需 token
- local:从 `~/.reproagent/data/` 读取本地 parquet

#### 指标与图表 `reproducer/metrics.py`

```python
def compute_ic(factor_values: pl.DataFrame, forward_returns: pl.DataFrame) -> pl.DataFrame:
    """截面 rank IC(按日期),返回 [date, ic]。"""

def compute_group_returns(grouped: pl.DataFrame, returns: pl.DataFrame, num_groups: int) -> dict[int, float]:
    """计算各分组年化收益。"""

def compute_sharpe(returns: pl.Series, freq: str = "daily") -> float:
    """夏普比率;日频年化因子 √252。"""

def compute_max_drawdown(equity_curve: pl.Series) -> float:
    """最大回撤。"""

def generate_charts(backtest_result: BacktestResult, output_dir: Path) -> list[Path]:
    """生成净值曲线图、分组收益柱状图、IC 时序图,返回图片路径列表。"""
```

---

### 子系统 4:偏差控制与自愈 `deviation/`

#### Protocol

**`deviation/protocol.py`**

```python
class DeviationAnalyzerProtocol(Protocol):
    def analyze(
        self, reproduced: BacktestResult, reported: ReportedMetrics,
        tolerances: ToleranceConfig,
    ) -> DeviationReport:
        """对比复现值 vs 研报值,设置 .passed 和 .metric_deviations。"""
        ...

    def classify_root_cause(
        self, deviation: DeviationReport, config: ReplicationConfig
    ) -> RootCause:
        """分类偏差根因,复杂情况可调 LLM。"""
        ...

    def should_reflect(
        self, deviation: DeviationReport, state: ReflectionState
    ) -> bool:
        """True = 根因可修正 AND 还有迭代次数 AND 偏差仍在改善。"""
        ...
```

#### 偏差分析器 `deviation/analyzer.py`

```python
class DeviationAnalyzer:
    def analyze(
        self, reproduced: BacktestResult, reported: ReportedMetrics,
        tolerances: ToleranceConfig,
    ) -> DeviationReport:
        deviations = {}

        if reported.ic_mean is not None:
            delta = reproduced.ic_mean - reported.ic_mean
            deviations["ic_mean"] = abs(delta)

        if reported.ic_ir is not None:
            delta = reproduced.ic_ir - reported.ic_ir
            deviations["ic_ir"] = abs(delta)

        if reported.long_short_return is not None:
            delta_rel = abs(reproduced.long_short_annual_return - reported.long_short_return)
            deviations["long_short_return"] = delta_rel / max(abs(reported.long_short_return), 1e-9)

        if reported.sharpe_ratio is not None:
            deviations["sharpe"] = abs(reproduced.sharpe_ratio - reported.sharpe_ratio)

        if reported.max_drawdown is not None:
            deviations["max_drawdown"] = abs(reproduced.max_drawdown - reported.max_drawdown)

        passed = (
            deviations.get("ic_mean", 0) <= tolerances.ic_mean_abs
            and deviations.get("ic_ir", 0) <= tolerances.ic_ir_abs
            and deviations.get("long_short_return", 0) <= tolerances.long_short_return_rel
            and deviations.get("sharpe", 0) <= tolerances.sharpe_abs
            and deviations.get("max_drawdown", 0) <= tolerances.max_drawdown_abs
        )

        return DeviationReport(
            id=uuid4().hex, comparison_id=uuid4().hex,
            factor_id=reproduced.factor_id, passed=passed,
            metric_deviations=deviations, tolerances=tolerances,
        )
```

#### 容忍区间 `deviation/tolerances.py`

> **业界标准容忍区间**(来自 DolphinDB、qlib、alpha-lens、bagel-factor 文档):

```python
# IC(absolute):
#   < 0.01 弱 | 0.01-0.03 可接受 | 0.03-0.05 强 | > 0.05 极强
#   容忍:ΔIC 绝对值 ≤ 0.02-0.03
#
# ICIR:
#   < 0.2 弱 | 0.2-0.5 可接受 | 0.5-1.0 强 | > 1.0 极强
#   容忍:ΔICIR 绝对值 ≤ 0.1-0.2
#
# Sharpe:
#   < 0.5 弱 | 0.5-1.0 可接受 | 1.0-1.5 强 | > 1.5 极强
#   容忍:相对偏差 15-20%;Bailey DSR 校正多重检验后用 20%
#
# Max Drawdown:绝对值 ±5%(更宽松,可到 ±10%)
#
# Annualized Return:相对偏差 10-15%(含交易成本)
#
# IC Hit Rate:< 50% 弱 | 50-55% 可接受 | 55-65% 强 | > 65% 极强
```

| 指标 | 弱 | 可接受 | 强 | 极强 | 容忍 ε |
|---|---|---|---|---|---|
| IC(Pearson) | <0.01 | 0.01-0.03 | 0.03-0.05 | >0.05 | ±0.03 |
| IC(Rank/Spearman) | <0.01 | 0.02-0.04 | 0.04-0.06 | >0.06 | ±0.03 |
| ICIR | <0.2 | 0.2-0.5 | 0.5-1.0 | >1.0 | ±0.2 |
| Sharpe | <0.5 | 0.5-1.0 | 1.0-1.5 | >1.5 | 相对 15-20% |
| IC Hit Rate | <50% | 50-55% | 55-65% | >65% | 缺乏惯例 |
| Max DD | — | — | — | — | 绝对 ±5% |
| 年化收益 | — | — | — | — | 相对 10-15% |

> **进阶防过拟合**(参考 alpha-lens):结合 Deflated Sharpe Ratio(DSR 校正 N 次实验 + 非正态)、Probability of Backtest Overfitting(PBO)、Min Backtest Length、Walk-Forward 一致性、Bootstrap Sharpe CI,输出一个 Production Readiness Score(0-100)。< 20 大概率过拟合,> 80 生产就绪。

#### 根因分类 `deviation/root_cause.py`

```python
def classify_root_cause(
    deviation: DeviationReport, config: ReplicationConfig
) -> RootCause:
    """启发式规则 + 可选 LLM:
    - IC 方向反了 → LOOKAHEAD_BIAS
    - 所有指标整体偏高/偏低 → DATA_MISMATCH(数据源/字段映射)
    - 部分指标匹配但 IC 差距大 → FORMULA_ERROR
    - IC 匹配但收益偏差大 → PARAMETER_ERROR(频率/窗口)
    - 规则不命中 → LLM 分析 → UNKNOWN fallback
    """
```

#### 反思循环控制器 `deviation/reflection_loop.py`

> **核心:** cap N=3,持久化每步以支持崩溃恢复,防震荡(连续 2 次无改善即终止)。

```python
class ReflectionLoopController:
    def __init__(
        self, reproducer: FactorReproducerProtocol,
        analyzer: DeviationAnalyzerProtocol,
        llm_extractor: LLMExtractor, config_builder: ConfigBuilder,
        tolerances: ToleranceConfig, repository: Repository,
    ):
        self.reproducer = reproducer
        self.analyzer = analyzer
        self.llm_extractor = llm_extractor
        self.config_builder = config_builder
        self.tolerances = tolerances
        self.repository = repository

    def run(
        self, initial_config: ReplicationConfig, reported: ReportedMetrics
    ) -> ReflectionState:
        state = ReflectionState(
            id=uuid4().hex, factor_id=initial_config.factor_specs[0].id,
            report_id=initial_config.report_id,
            original_config=initial_config, max_iterations=3,
        )
        self.repository.save_reflection_state(state)  # 立即持久化,崩溃可恢复

        current_config = initial_config
        prev_deviation_score = float("inf")
        no_improvement_streak = 0

        for iteration in range(state.max_iterations):
            # 1. 用当前配置复现
            result = self.reproducer.reproduce(current_config)

            # 2. 分析偏差
            deviation = self.analyzer.analyze(result, reported, self.tolerances)
            deviation.root_cause = self.analyzer.classify_root_cause(deviation, current_config)
            deviation.recommend_reflect = self.analyzer.should_reflect(deviation, state)

            # 3. 记录步骤(立即持久化)
            step = ReflectionStep(
                id=uuid4().hex, state_id=state.id, iteration=iteration,
                prompt="", response="",
                revised_config=current_config, deviation_report=deviation,
            )
            state.steps.append(step)
            state.current_iteration = iteration
            self.repository.save_reflection_step(step)

            # 4. 收敛检查
            score = self._deviation_score(deviation)
            if deviation.passed:
                state.status = "converged"
                state.best_deviation_score = score
                state.best_step_id = step.id
                break

            # 5. 防震荡检测
            if score >= prev_deviation_score:
                no_improvement_streak += 1
                if no_improvement_streak >= 2:
                    state.status = "escalated"
                    break
            else:
                no_improvement_streak = 0
            prev_deviation_score = score

            # 6. 反思是否值得
            if not deviation.recommend_reflect:
                state.status = "escalated"
                break

            # 7. 构建反思 prompt(含完整历史)并生成修订配置
            prompt = self._build_reflection_prompt(state, deviation)
            revised_spec = self.llm_extractor.revise(prompt, current_config.factor_specs[0])
            report = self.repository.get_report(state.report_id)
            current_config = self.config_builder.build_config([revised_spec], report)
            step.prompt = prompt
            step.response = revised_spec.model_dump_json()
            self.repository.save_reflection_step(step)
        else:
            state.status = "exhausted"

        state.updated_at = datetime.utcnow()
        self.repository.save_reflection_state(state)
        return state

    def _deviation_score(self, deviation: DeviationReport) -> float:
        """归一化偏差得分:各指标偏差/容忍度的平方和开方。"""
        score = 0.0
        for metric, delta in deviation.metric_deviations.items():
            tol = self._get_tolerance(metric, deviation.tolerances)
            if tol > 0:
                score += (delta / tol) ** 2
        return score ** 0.5

    def _build_reflection_prompt(
        self, state: ReflectionState, latest_deviation: DeviationReport
    ) -> str:
        """构建反思 prompt,包含完整历史以避免重复震荡。使用 prompts.py 的 Jinja2 模板。"""
        from .prompts import REFLECTION_PROMPT
        return REFLECTION_PROMPT.render(
            original_spec=state.original_config.factor_specs[0],
            history=state.steps, latest_deviation=latest_deviation,
        )
```

**关键设计点:**
- **N=3 硬上限**:在 `state.max_iterations` 中配置,for 循环 range 保证
- **崩溃恢复**:每步立即 `save_reflection_step`,状态更新后立即 `save_reflection_state`
- **防震荡**:连续 2 次偏差得分无改善 → 提前终止并升级到 `escalated`
- **线程化上下文**:每次反思 prompt 包含完整历史(所有迭代的公式、偏差、根因),LLM 可看到自己的震荡并自纠

---

### 子系统 5:因子库管理层 `library/`

#### Protocol

**`library/protocol.py`**

```python
class FactorLibraryProtocol(Protocol):
    def register(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        """持久化 + 去重检查 + 版本 bump。
        副作用:更新 INDEX.md 和 wiki。"""
        ...

    def get(self, factor_id: str) -> FactorLibraryEntry | None: ...

    def list(self, filter: LibraryFilter | None = None) -> list[FactorLibraryEntry]: ...

    def dedup_check(self, entry: FactorLibraryEntry) -> FactorLibraryEntry | None:
        """dedup_hash 命中 → 返回已有 entry,否则 None。"""
        ...

    def update_index(self) -> None:
        """从全部 entries 重生成全局 INDEX.md。"""
        ...

    def update_wiki(self) -> None:
        """从 entries 生成逐因子 Markdown wiki 页。"""
        ...
```

#### 管理器 `library/manager.py`

```python
class FactorLibraryManager:
    def register(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        # 1. 去重检查
        existing = self.dedup_check(entry)
        if existing:
            # 版本 bump(semver patch)
            entry.version = self.versioning.bump(existing.version, "patch")
            entry.status = "ready"
        # 2. 风格分类
        entry.factor.style = self.classifier.classify(entry.factor)
        # 3. 入库(SQLModel)
        self.repository.save_library_entry(entry)
        # 4. 更新 INDEX.md
        self.index_writer.update()
        # 5. 更新 wiki
        self.wiki_writer.update()
        return entry
```

#### 版本与去重 `library/versioning.py`

```python
def compute_dedup_hash(factor: FactorDefinition) -> str:
    """sha256(formula + sorted(input_fields))。"""
    import hashlib
    key = factor.formula + "|" + "|".join(sorted(factor.input_fields))
    return hashlib.sha256(key.encode()).hexdigest()

def bump(version: str, level: Literal["major", "minor", "patch"]) -> str:
    """semver bump。"""
```

#### 风格分类 `library/classifier.py`

```python
class StyleClassifier:
    """规则优先 + LLM fallback。"""
    RULES = {
        "momentum": ["动量", "momentum", "ret", "return", "涨跌"],
        "value": ["估值", "value", "PE", "PB", "市盈率", "市净率"],
        "quality": ["质量", "quality", "ROE", "ROA", "盈利"],
        "volatility": ["波动", "volatility", "vol", "std"],
        "liquidity": ["流动性", "liquidity", "turnover", "换手", "成交"],
        "size": ["市值", "size", "cap", "规模"],
        "growth": ["成长", "growth", "增长", "YoY"],
    }

    def classify(self, factor: FactorDefinition) -> str:
        # 1. 关键词规则匹配
        for style, keywords in self.RULES.items():
            if any(kw in factor.name or kw in factor.formula for kw in keywords):
                return style
        # 2. LLM fallback(用 settings 中的模型)
        return self._llm_classify(factor)
```

#### INDEX 与 Wiki 生成

**`library/index_writer.py`**

```python
def update_index() -> None:
    """重生成 ~/.reproagent/wiki/INDEX.md:
    表格:| 因子名 | 风格 | 来源研报 | 版本 | 偏差通过 | 创建时间 |
    按 created_at 倒序。"""
```

**`library/wiki_writer.py`**

```python
def update_wiki() -> None:
    """为每个因子生成 ~/.reproagent/wiki/factors/<factor_name>.md:
    # 因子名(中文)
    ## 基本信息
    ## 公式
    ## 输入字段
    ## 回测结果(IC、分组收益、净值曲线图)
    ## 来源研报
    ## 复现偏差
    """
```

---

### 子系统 6:前端展示 `tui/`

> Textual 是 async-native 的现代终端 UI 框架,有 CSS 主题、命令面板、丰富 widget 集。Rich 只是输出库,不支持交互。

#### 应用骨架 `tui/app.py`

```python
from textual.app import App, ComposeResult

class ReproAgentApp(App):
    """ReproAgent TUI 主应用。"""
    TITLE = "ReproAgent"
    SUB_TITLE = "研报因子复现系统"
    BINDINGS = [
        ("q", "quit", "退出"),
        ("d", "toggle_dark", "深色/浅色"),
        ("r", "reproduce", "复现研报"),
        ("l", "library", "因子库"),
        ("v", "review", "人工复核"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield TabbedContent(
            TabPane("复现", ReportReproductionScreen()),
            TabPane("因子库", FactorLibraryScreen()),
            TabPane("人工复核", ManualReviewScreen()),
        )
```

#### 页面 `tui/screens/`

**研报复现页 `reproduction.py`**
```python
class ReportReproductionScreen(Screen):
    """上传 PDF / 输入路径 → 触发复现 → 显示进度和结果。"""
```

**因子库浏览器 `library_browser.py`**
```python
class FactorLibraryScreen(Screen):
    """树视图浏览因子库,右侧显示指标和图表。"""
```

**人工复核 `review.py`**
```python
class ManualReviewScreen(Screen):
    """列出人工复核队列,支持 approve/reject。"""
```

#### TUI ↔ 领域层桥接(async → sync)

**关键:** Textual 是 async,但领域层是 sync。用 `anyio.to_thread.run_sync` 桥接。

```python
from anyio.to_thread import run_sync

async def reproduce_async(self, config: ReplicationConfig) -> BacktestResult:
    """TUI 调用:在线程中跑 sync 领域逻辑,不阻塞事件循环。"""
    return await run_sync(reproducer.reproduce, config)
```

---

## 4. 横切关注点

### 4.1 配置与密钥 `settings.py`

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    # LLM
    llm_provider: Literal["openai", "anthropic"] = "anthropic"
    llm_api_key: SecretStr
    llm_model: str = "claude-sonnet-4-5"
    llm_vision_model: str = "claude-sonnet-4-5"
    llm_temperature: float = 0.0
    llm_seed: int = 42

    # Parser
    parser_backend: Literal["marker", "llamaparse", "mineru"] = "marker"
    parser_version: str = "1.0.0"

    # Data
    data_source: Literal["ricequant", "tushare", "local"] = "ricequant"
    ricequant_token: SecretStr | None = None
    tushare_token: SecretStr | None = None

    # 存储
    data_dir: Path = Path("~/.reproagent").expanduser()
    db_path: Path = data_dir / "reproagent.db"
    cache_dir: Path = data_dir / "cache"
    reports_dir: Path = data_dir / "reports"
    factors_dir: Path = data_dir / "factors"
    wiki_dir: Path = data_dir / "wiki"
    logs_dir: Path = data_dir / "logs"

    # 反思
    max_reflection_iterations: int = 3

    # TUI
    tui_theme: str = "dark"
```

### 4.2 日志 `logging_setup.py`

```python
from loguru import logger

def setup_logging(settings: Settings) -> None:
    logger.remove()
    logger.add(
        settings.logs_dir / "reproagent.log",
        rotation="10 MB", retention="30 days", compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
    )
    logger.add(sys.stderr, level="INFO")
```

### 4.3 持久化 `persistence/`

| 关注点 | 选择 | 理由 |
|---|---|---|
| DB | SQLite via SQLModel | 单用户、关系查询、Pydantic v2 兼容、零部署 |
| 大数据 | Parquet 文件 | 因子值、净值曲线宽表,Polars 原生,列式压缩 |
| 配置导出 | YAML | 人类可读、Git 可 diff、ML 标配 |
| 领域 ↔ DB 映射 | 分离的 SQLModel 表类 `tables.py` | 领域模型保持持久化无关;避免 `table=True` 泄漏 |
| 迁移 | Alembic(后续) | 初期 `create_all()`,schema 稳定后引入 |

**文件系统布局 `persistence/paths.py`:**

```
~/.reproagent/
├── reproagent.db                       # SQLite(元数据、库、反思状态)
├── cache/
│   └── <sha256前16位>/
│       ├── markdown/report.md          # 布局提取输出
│       ├── specs.json                   # ParsedFactorSpec[]
│       ├── config.yaml                 # ReplicationConfig
│       └── backtest/
│           ├── factor_values.parquet
│           └── equity_curve.parquet
├── reports/
│   └── <report_id>/
│       ├── original.pdf
│       ├── parsed.md
│       └── config.yaml
├── factors/
│   └── <factor_id>/
│       ├── definition.json
│       ├── factor_values.parquet
│       └── backtest/
│           ├── equity_curve.parquet
│           └── metrics.json
├── wiki/
│   ├── INDEX.md
│   └── factors/
│       └── <factor_name>.md
└── logs/
    └── reproagent.log
```

**SQLModel 表映射 `persistence/tables.py`:**

```python
from sqlmodel import SQLModel, Field, Field
from datetime import datetime

class ReportTable(SQLModel, table=True):
    __tablename__ = "reports"
    id: str = Field(primary_key=True)
    file_hash: str = Field(index=True)
    file_path: str
    title: str | None = None
    broker: str | None = None
    report_date: str | None = None
    page_count: int
    validation_status: str
    ingested_at: str

class FactorLibraryTable(SQLModel, table=True):
    __tablename__ = "factor_library"
    id: str = Field(primary_key=True)
    factor_json: str                     # 序列化的 FactorDefinition
    report_id: str = Field(foreign_key="reports.id")
    config_id: str
    backtest_result_id: str
    deviation_passed: bool
    status: str
    version: str
    dedup_hash: str = Field(index=True)
    tags_json: str
    created_at: str

class ReflectionStateTable(SQLModel, table=True):
    __tablename__ = "reflection_states"
    id: str = Field(primary_key=True)
    factor_id: str = Field(index=True)
    report_id: str
    state_json: str                       # 完整序列化的 ReflectionState
    created_at: str
    updated_at: str

class ManualReviewQueueTable(SQLModel, table=True):
    __tablename__ = "manual_review_queue"
    id: str = Field(primary_key=True)
    report_id: str = Field(foreign_key="reports.id")
    reason: str
    status: str                           # pending / approved / rejected
    created_at: str
```

### 4.4 缓存 `cache/`

**缓存 key 计算 `cache/cache_key.py`:**

```python
def compute_cache_key(
    pdf_hash: str, parser_version: str, extraction_model_id: str
) -> str:
    """缓存 key = sha256(pdf_hash + parser_version + extraction_model_id) 截断 16 位。
    parser/model 版本变化 → key 变化 → 缓存失效。"""
    import hashlib
    raw = f"{pdf_hash}|{parser_version}|{extraction_model_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

**缓存管理 `cache/cache_manager.py`:**

```python
class CacheManager:
    def get_cached(self, cache_key: str) -> tuple[str, list[ParsedFactorSpec], ReplicationConfig] | None:
        """命中 → 返回(markdown, specs, config);未命中 → None。"""

    def get_cached_backtest(self, cache_key: str, factor_id: str) -> BacktestResult | None:
        """命中 → 返回缓存回测结果;否则 None。"""

    def save(self, cache_key: str, markdown: str, specs: list[ParsedFactorSpec],
             config: ReplicationConfig, backtest_result: BacktestResult | None = None) -> None:
        """保存缓存到 ~/.reproagent/cache/<cache_key>/。"""
```

- 用文件系统缓存(而非 SQLite blob):产物大(PDF、parquet、markdown),SQLite blob 膨胀且无法 lazy load

### 4.5 并发架构

**架构:同步领域层 + async TUI 桥接**

```
TUI (async, Textual)
  │
  ├── anyio.to_thread.run_sync(reproducer.reproduce(config))
  │     │
  │     ▼ (sync 线程)
  │   FactorReproducer.reproduce()
  │     ├── PolarsEngine.compute()        # CPU 密集, sync
  │     ├── StrategyBacktester.run()      # CPU 密集, sync
  │     └── LLM 调用(sync client)         # I/O 密集, 阻塞线程(不阻塞事件循环)
  │
  └── UI 更新通过 Textual reactive 系统
```

- **领域层(parser、reproducer、deviation、library):同步**。CPU 密集(Polars、回测)或单次 I/O(LLM)。sync 简单可测。
- **TUI 层:async(Textual 要求)**。用 `anyio.to_thread.run_sync` 包装 sync 领域调用。
- **CLI 层:sync(Typer)**。
- **LLM 调用:用 sync client**(`openai.OpenAI()` 非 `AsyncOpenAI()`)。CLI 中阻塞即可;TUI 中线程包装处理非阻塞。

---

## 5. CLI 命令 `cli.py`

> Typer,类型提示原生,Rich 集成。

```python
import typer
app = typer.Typer(name="reproagent", help="研报因子复现系统")


@app.command()
def ingest(pdf_path: Path):
    """摄入一篇研报。"""
    report = upload_pdf(pdf_path)
    report = validate_pdf(report)
    if report.validation_status == "invalid":
        typer.echo(f"校验失败: {report.validation_errors}")
        raise typer.Exit(1)
    typer.echo(f"摄入成功: {report.id} ({report.page_count} 页)")


@app.command()
def reproduce(pdf_path: Path):
    """端到端:摄入 → 解析 → 复现 → 偏差 → 入库。"""
    # 完整流程编排
    ...


@app.command()
def library(style: str | None = None):
    """浏览因子库。"""
    ...


@app.command()
def review():
    """处理人工复核队列。"""
    ...


@app.command()
def tui():
    """启动 TUI。"""
    from reproagent.tui.app import ReproAgentApp
    ReproAgentApp().run()
```

---

## 6. 依赖清单 `pyproject.toml`

```toml
[project]
name = "reproagent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Core
    "pydantic>=2.5",
    "pydantic-settings>=2.1",
    "sqlmodel>=0.0.16",
    "pyyaml>=6.0",
    "loguru>=0.7",
    "jinja2>=3.1",
    # Parser
    "marker-pdf>=1.0",            # 可选,GPU 建议
    "llama-parse>=0.4",           # 可选,云端
    "pypdf>=4.0",
    "pdf2image>=1.17",            # PDF → 图片 for vision
    # LLM
    "openai>=1.40",               # structured outputs
    "anthropic>=0.30",            # Claude 备选
    "instructor>=1.0",            # 可选,自动重试
    # Reproducer
    "polars>=1.0",
    "rqalpha>=6.1",               # 回测引擎
    # TUI / CLI
    "textual>=0.50",
    "typer>=0.12",
    "rich>=13.0",
    # Utils
    "matplotlib>=3.8",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.5", "mypy>=1.10"]
mineru = ["magic-pdf>=0.8"]       # MinerU 备选

[project.scripts]
reproagent = "reproagent.cli:app"
```

---

## 7. 测试策略 `tests/`

```
tests/
├── conftest.py                   # 全局 fixtures(样例 PDF、mock LLM)
├── conformance/
│   └── test_engine_parity.py     # Polars vs rqalpha 引擎一致性
├── fixtures/
│   └── sample_reports/           # 真实研报样本
├── unit/
│   ├── test_parser.py
│   ├── test_reproducer.py
│   ├── test_deviation.py
│   └── test_library.py
└── integration/
    └── test_e2e.py               # 端到端:PDF → 入库
```

### 引擎一致性测试 `conformance/test_engine_parity.py`

```python
"""验证 PolarsEngine 和 RiceQuantEval 对同一因子产出相同结果。
防止因 NaN 处理、forward-fill、groupby 语义差异导致偏差分析失真。"""

@pytest.mark.parametrize("factor_name", ["momentum_20d", "roe_ttm", "turnover_20d"])
def test_engine_parity(factor_name):
    config_polars = make_config(engine="polars", factor=factor_name)
    config_rqalpha = make_config(engine="rqalpha", factor=factor_name)
    result_p = PolarsEngine(config_polars).compute(...)
    result_r = RiceQuantEval(config_rqalpha).compute(...)
    # 列式对齐后比较
    assert_values_match(result_p, result_r, tol=1e-6)
```

---

## 8. Top 5 架构风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| **1** | **LLM 提取非确定性**:同 PDF + 同 prompt → 不同因子 spec,破坏可复现性 | `temperature=0.0` + 固定 seed + 缓存提取结果。structured outputs 严格模式。校验失败重试 1 次后仍失败 → 人工复核队列 |
| **2** | **Marker/LlamaParse 版本漂移**:更新后 Markdown 格式变化,缓存失效 | 缓存 key 含 `parser_version`;`pyproject.toml` 固定版本;`ReplicationConfig.parser_version` 字段让旧配置在 parser 升级时可重处理 |
| **3** | **Polars vs rqalpha 因子值偏移**:NaN 处理、forward-fill、groupby 语义差异 → 偏差分析失真 | `FactorEngine` Protocol + `tests/conformance/` 一致性测试,CI 中对标准因子断言两引擎值差异 < 1e-6 |
| **4** | **反思循环震荡**:LLM 在两个配置间重复不收敛,浪费 3 次迭代 | 追踪 `best_deviation_score`;连续 2 次无改善 → 提前 break + escalate;每次反思 prompt 含完整历史让 LLM 自识别震荡 |
| **5** | **Vision 模型对低质扫描 PDF 幻觉**:A 股研报常为扫描件,公式在图片中,mix 中英文 → 公式看似合理实则错误 | `extraction_confidence > 0.7` 阈值,低置信直接进人工复核(跳过反思);公式语法校验(LaTeX 可解析、引用变量都在数据字典中);TUI 复核页面显示源页截图供人工核对 |

---

## 9. 端到端流程编排(流程图与代码映射)

> 主入口:CLI `reproduce` 命令 或 TUI 的"复现研报"操作。

```python
def reproduce_report(pdf_path: Path, settings: Settings) -> None:
    # === 子系统 1: 摄入 ===
    report = upload_pdf(pdf_path)
    report = validate_pdf(report)
    if report.validation_status == "invalid":
        enqueue_manual_review(report, "PDF 校验失败")
        notify_frontend("error", report)
        return

    # === 缓存检查 ===
    cache_key = compute_cache_key(report.file_hash, settings.parser_version, settings.llm_vision_model)
    cached = CacheManager().get_cached(cache_key)
    if cached:
        markdown, specs, config = cached
        cached_bt = CacheManager().get_cached_backtest(cache_key, specs[0].id)
        if cached_bt:
            notify_frontend("cache_hit", cached_bt)
            return

    # === 子系统 2: 解析 ===
    parser = ReportParser(settings)
    if not cached:
        specs = parser.parse(report)             # 布局 → LLM → 校验
        config = parser.build_config(specs, report)
        CacheManager().save_markdown_specs_config(cache_key, ...)
    else:
        specs = parser.schema_validator.validate_all(specs)  # 重校验

    # 检查提取置信度
    for spec in specs:
        if spec.extraction_confidence < 0.7:
            enqueue_manual_review(report, f"因子 {spec.factor_name} 提取置信度过低")
            return

    # === 子系统 3: 复现 ===
    reproducer = FactorReproducer(settings, data_loader)
    result = reproducer.reproduce(config)

    # === 子系统 4: 偏差 ===
    analyzer = DeviationAnalyzer()
    tolerances = ToleranceConfig()
    deviation = analyzer.analyze(result, specs[0].reported_metrics, tolerances)
    deviation.root_cause = analyzer.classify_root_cause(deviation, config)

    if deviation.passed:
        # === 子系统 5: 入库 ===
        entry = FactorLibraryEntry(
            factor=factor_def, report_id=report.id, config_id=config.id,
            backtest_result_id=result.id, deviation_passed=True,
            version="1.0.0", dedup_hash=compute_dedup_hash(factor_def),
        )
        FactorLibraryManager().register(entry)
        notify_frontend("registered", entry)
    else:
        # 偏差超容忍 → 反思循环
        if analyzer.should_reflect(deviation, ReflectionState(max_iterations=3)):
            controller = ReflectionLoopController(reproducer, analyzer, ...)
            state = controller.run(config, specs[0].reported_metrics)
            if state.status == "converged":
                # 收敛 → 取最佳步骤的配置 → 重新入库
                best_config = state.steps[int(state.best_step_id)].revised_config
                # ... register
            else:
                # 不收敛 → 人工复核队列
                enqueue_manual_review(report, f"反思未收敛: {state.status}")
                notify_frontend("human_review", report)
        else:
            enqueue_manual_review(report, f"不值得反思: {deviation.root_cause}")
            notify_frontend("human_review", report)

    # === 子系统 6: 通知前端 ===
    notify_frontend("done", report)
```

---

## 10. 实现顺序建议(给 coding agent)

按依赖关系自底向上,每步可独立测试:

1. **Phase 0:脚手架** — `pyproject.toml`、`settings.py`、`logging_setup.py`、`exceptions.py`、目录结构
2. **Phase 1:领域模型** — `models/` 全部(纯 Pydantic,无外部依赖,可单测)
3. **Phase 2:持久化** — `persistence/`(SQLModel 表、repository、paths)
4. **Phase 3:摄入** — `ingestion/`(uploader、validator、review_queue)
5. **Phase 4:缓存** — `cache/`(cache_key、cache_manager)
6. **Phase 5:解析** — `parser/`(先 layout_extractor 用 Marker,再 llm_extractor,再 schema_validator,再 config_builder)
7. **Phase 6:复现** — `reproducer/`(data_loader、evaluator_factory、polars_engine、backtester、metrics;rqalpha_engine 后做)
8. **Phase 7:偏差** — `deviation/`(analyzer、tolerances、root_cause、reflection_loop)
9. **Phase 8:因子库** — `library/`(versioning、classifier、index_writer、wiki_writer)
10. **Phase 9:CLI** — `cli.py`(Typer 命令)
11. **Phase 10:TUI** — `tui/`(app、screens、widgets;最后做,依赖前面所有层)
12. **Phase 11:测试与一致性** — `tests/conformance/` 引擎一致性测试

---

## 附录 A:Pydantic v2 结构化提取最佳实践

```python
from pydantic import BaseModel, Field, field_validator, model_validator

class FactorExtraction(BaseModel):
    factor_name: str = Field(description="因子名称")
    formula: str = Field(description="数学公式")
    parameters: list[dict] = Field(default_factory=list)
    reported_ic: float | None = None
    review_required: bool = False
    review_notes: list[str] = []

    @field_validator('factor_name')
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode='after')
    def validate_completeness(self):
        if not self.factor_name:
            self.review_required = True
            self.review_notes.append("因子名缺失")
        return self

# OpenAI Structured Outputs
response = client.beta.chat.completions.parse(
    model="gpt-4o-2024-08-06",     # 必须此版本或更新
    messages=[...],
    response_format=FactorExtraction,  # 传类,非实例
)
factor = response.choices[0].message.parsed
```

**关键:**
- 所有字段必须 required(用 `None` 表示可选,不用 `Optional` 语法糖)
- 传 **类**,不是实例
- 校验失败用 `instructor` 库自动重试并在 prompt 注入错误信息

## 附录 B:Polars 时序因子计算速查

```python
import polars as pl

lf = pl.scan_parquet("prices/*.parquet")  # lazy,不立即加载

# 每股 20 日收益率(面板感知 over)
result = (
    lf.sort(["trade_date", "ts_code"])
    .with_columns([
        pl.col("close").pct_change(1).alias("daily_return"),
        pl.col("close").pct_change(20).over("ts_code").alias("ret_20d"),
        pl.col("volume").rolling_mean(20).over("ts_code").alias("vol_20d"),
    ])
    .filter(pl.col("ret_20d").is_not_null())
)
df = result.collect()  # 触发执行

# 动态时间窗口分组(5 日滚动均值,按 trade_date 锚定)
df.group_by_dynamic(
    "trade_date", every="1d", period="5d", closed="left",
    group_by="ts_code", include_boundaries=True,
).agg(pl.col("close").mean().alias("close_ma5"))

# Polars ↔ pandas 零拷贝
pd_df = df.to_pandas()
pl_df = pl.from_pandas(pd_df)
```

**陷阱:**
- `group_by_dynamic` 要求索引列升序排序
- `over("ts_code")` 面板感知:按股票滚动,无需显式 group_by
- LazyFrame `collect()` 才执行,之前都在构建计划

## 附录 C:rqalpha 回测 API 速查

```python
from rqalpha import run_func

def init(context):
    context.s1 = "000001.XSHE"
    context.fired = False

def handle_bar(context, bar_dict):
    if not context.fired:
        order_percent(context.s1, 1)
        context.fired = True

config = {
    "base": {
        "start_date": "2020-01-01", "end_date": "2020-12-31",
        "benchmark": "000300.XSHG", "accounts": {"stock": 100000},
    },
    "extra": {"log_level": "warning"},
    "mod": {"sys_analyser": {"enabled": True, "plot": True}},
}

result = run_func(init=init, handle_bar=handle_bar, config=config)
print(f"总收益: {result['summary']['total_returns']:.2%}")
```

**关键 API:**
- `history_bars(symbol, n, frequency, field)` — 历史 K 线
- `order_percent(symbol, percent)` — 目标仓位 %
- Mod 系统:自定义因子 Hook,[rqalpha Mod Hooks](https://rqalpha.readthedocs.io/zh-cn/latest/intro/hook.html)
- `rqalpha download-bundle` 下载免费日频 A 股数据
- 开源版:日频 + 回测;分钟/Tick 需付费 RiceQuant 订阅

---

*本 masterplan 综合了 Oracle 架构设计、两轮 Librarian 外部库调研,以及业界容忍标准与参考架构。每文件每方法可直接编码实现。*