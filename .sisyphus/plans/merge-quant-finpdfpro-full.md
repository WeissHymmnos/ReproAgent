# Merge 量化agent + finpdfpro → reproagent 全量实现

## TL;DR

> **Quick Summary**: 将 `finpdfpro`（`finreportparser`）vendoring 进 `src/finreportparser` 作为唯一 PDF 布局后端；将 `量化agent.zip` 原样放入 `legacy_quant` 旁路；按 `masterplan.md` 填满 reproagent 全部业务桩（摄入/解析/复现/偏差/因子库/TUI/CLI/pipeline），数据后端对齐 aiminer（ricequant | qlib | local）。
>
> **Deliverables**:
> - `src/finreportparser/` vendored + configs + 路径修复
> - `src/reproagent/legacy_quant/`（zip 三文件 + 相对导入）
> - masterplan 6 子系统 + pipeline + CLI 全命令可运行
> - HTML 因子库仪表盘 + 完整 Textual TUI
> - pytest（tests-after）+ Agent QA 证据
>
> **Estimated Effort**: XL
> **Parallel Execution**: YES — 8 waves（Wave0 阻塞，其后最大并行）
> **Critical Path**: W0 vendor → W1 persistence → W2 parser → W3 reproducer → W5 pipeline → W6 CLI → W7 e2e

---

## Context

### Original Request
把 `~/Documents/量化agent.zip` 合并到本项目并补齐除 PDF 解析外的所有功能；PDF 解析使用 `~/Documents/finpdfpro`。

### Interview Summary
**Key Discussions**:
- 交付档位: **masterplan 全量实现**
- finpdfpro: **Vendoring 到 `src/finreportparser` 并列包**
- zip: **`legacy_quant` 原样旁路**（不重写进 Protocol）
- 前端: **HTML 仪表盘 + masterplan 完整 TUI**
- 测试: **pytest 测试后** + Agent QA
- LLM: **真实 API + 无 key mock fallback**
- 数据: **与 aiminer 相同** — ricequant | qlib | local + evaluator_factory

**Research Findings**:
- reproagent: 脚手架 + 领域模型；约 62 处 `NotImplementedError`
- 量化agent.zip: 因子发现 / 偏差控制 / HTML 仪表盘（无 PDF）
- finpdfpro: `parse_pdf() → DocumentResult`，~4800 LOC
- aiminer: `build_evaluator` + `local_data` + `polars_engine` 可移植；**不**移植 swarm/RAG/wiki

### Metis Review
**Identified Gaps（已写入计划）**:
- finpdfpro `find_configs_dir()` vendoring 后路径会断 → 必须 vendor `configs/` 并修路径
- numpy: finpdfpro 钉 `<2`，reproagent 用 2.x → vendor 时放宽
- `DocumentResult` → `LayoutExtractor.extract() → str` 需要适配层
- Settings `data_source` 需加入 `qlib`（aiminer 模式）
- 必须有合成 OHLCV fixture，否则 local 后端无法 e2e
- 锁定范围: 不做 alpha-lens 进阶、不做完整 rqalpha 策略引擎、不移植 aiminer swarm/RAG

---

## Work Objectives

### Core Objective
在 reproagent 中完成「PDF 研报 → 因子提取 → 回测复现 → 偏差自愈 → 因子库」全链路，PDF 布局解析由 vendored finreportparser 提供，非 PDF 逻辑按 masterplan 实现并以 quant zip / aiminer 为参考。

### Concrete Deliverables
- `src/finreportparser/` + `configs/{default,fast,max_quality}.yaml`
- `src/reproagent/legacy_quant/{factor_db,factor_research_pipeline,factor_library_dashboard}.py`
- 已实现（非桩）: ingestion / parser / reproducer / deviation / library / persistence / cache / pipeline / cli / tui / utils
- `library/dashboard.py` HTML 导出
- `tests/fixtures/` 样例 PDF + OHLCV parquet
- 更新 `pyproject.toml` / `.env.example` / README

### Definition of Done
- [ ] `uv sync` 成功；`import finreportparser` 与 `import reproagent` 成功
- [ ] `python -c "from finreportparser.config import load_config; load_config()"` 不抛错
- [ ] `OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf` 在 mock+local 下跑完（exit 0 或明确入库/复核）
- [ ] `uv run pytest -q` 核心单测 + e2e 通过（无真实 LLM/RQ 凭证）
- [ ] `uv run reproagent library` / `review` / `tui` 不崩溃
- [ ] HTML 仪表盘可生成到 `~/.reproagent/` 或指定路径
- [ ] 业务路径中无残留阻塞性 `NotImplementedError`（除明确 optional 后端）

### Must Have
- finpdfpro 为默认且唯一主 PDF 布局后端
- masterplan 6 子系统可执行实现
- aiminer 式三数据后端（local 必可离线；ricequant/qlib lazy optional）
- LLM mock 离线可跑
- legacy_quant 隔离可运行
- HTML 仪表盘 + 完整 TUI 三屏

### Must NOT Have (Guardrails)
- 不自研 PDF 布局解析；不把 marker/llamaparse/mineru 作为主路径
- 不移植 aiminer LangGraph/RAG/wiki/agents/portfolio
- 不实现 alpha-lens DSR/PBO/MinBTL/walk-forward
- 不把 rqalpha 做成完整策略引擎（数据/评估薄封装即可）
- 不为 HTML 仪表盘建 Web 服务
- 不让 legacy_quant 与 core 双向深度耦合
- 不把 paddle/torch 做成 core 依赖
- 测试不得依赖真实 LLM key 或 RQ/qlib 凭证

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — 全部 agent 可执行验证。

### Test Decision
- **Infrastructure exists**: YES（pytest + ruff + mypy）
- **Automated tests**: YES（Tests-after）
- **Framework**: pytest via `uv run pytest`
- **Agent-Executed QA**: ALWAYS

### QA Policy
- CLI: `uv run reproagent ...`
- 库/模块: `uv run python -c "..."`
- TUI: Textual 测试 harness / 启动冒烟（非人工点屏）
- 证据: `.sisyphus/evidence/task-{N}-{slug}.txt`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (BLOCKING — vendor + deps + settings + fixtures):
├── Task 1: Vendor finreportparser + configs + path/numpy fix
├── Task 2: pyproject/deps + hatch packages + .env.example
├── Task 3: Settings 扩展 (finpdfpro/qlib/local)
├── Task 4: legacy_quant 旁路落地 + 相对导入
└── Task 5: 测试 fixtures (minimal PDF + OHLCV parquet)

Wave 1 (foundation — MAX PARALLEL after W0):
├── Task 6: utils/pdf.py
├── Task 7: persistence/repository + db session 完善
├── Task 8: cache/cache_manager
├── Task 9: utils/plotting.py
└── Task 10: ingestion uploader + validator + review_queue

Wave 2 (parser — after W0; partial after W1):
├── Task 11: LayoutExtractor finpdfpro 适配 (DocumentResult→md)
├── Task 12: LLMExtractor + mock fallback
├── Task 13: schema_validator + config_builder
└── Task 14: ReportParser 编排

Wave 3 (reproducer — after W0; aiminer patterns):
├── Task 15: data_loader (local/ricequant/qlib lazy)
├── Task 16: polars_engine (aiminer operators)
├── Task 17: metrics + backtester
├── Task 18: rqalpha/RiceQuant 薄封装 + evaluator_factory
└── Task 19: FactorReproducer 编排

Wave 4 (deviation + library — after W3 models ready):
├── Task 20: DeviationAnalyzer + root_cause
├── Task 21: library manager + classifier + index/wiki
└── Task 22: HTML dashboard (from zip)

Wave 5 (orchestration):
├── Task 23: ReflectionLoopController
├── Task 24: pipeline.reproduce_report
└── Task 25: logging_setup 完善（若仍为桩）

Wave 6 (interfaces):
├── Task 26: CLI 全命令接线
└── Task 27: TUI 三屏 + widgets 接线

Wave 7 (tests + QA):
├── Task 28: 子系统单测补齐
├── Task 29: e2e + 取消 skip
└── Task 30: README/依赖说明更新

Wave FINAL:
├── F1 Plan compliance (oracle)
├── F2 Code quality
├── F3 Real QA scenarios
└── F4 Scope fidelity
```

### Dependency Matrix

| Task | Blocked By | Blocks |
|------|------------|--------|
| 1-5 | — | 6-30 |
| 6 | 1-5 | 10 |
| 7 | 1-5 | 10,21,23,24 |
| 8 | 1-5 | 24 |
| 9 | 1-5 | 17,22 |
| 10 | 6,7 | 24,26 |
| 11 | 1-5 | 14 |
| 12 | 3 | 13,14,23 |
| 13 | 12 | 14 |
| 14 | 11,12,13 | 24 |
| 15 | 3 | 18,19 |
| 16 | 1-5 | 18,19 |
| 17 | 9 | 19 |
| 18 | 15,16 | 19 |
| 19 | 15-18 | 20,24 |
| 20 | 19 | 23,24 |
| 21 | 7 | 22,24 |
| 22 | 4,21 | 26 |
| 23 | 12,20,7 | 24 |
| 24 | 8,10,14,19,20,21,23 | 26,27,29 |
| 25 | 1-5 | 26 |
| 26 | 24 | 29 |
| 27 | 24 | 29 |
| 28 | 6-23 | 29 |
| 29 | 24,28 | FINAL |
| 30 | 2,26 | FINAL |

### Agent Dispatch Summary
- Wave 0: deep / unspecified-high
- Wave 1-4: mix quick + deep + unspecified-high
- Wave 5-6: deep
- Wave 7: unspecified-high
- FINAL: oracle + unspecified-high + deep

---

## TODOs

> Implementation + Test = ONE Task. Every task has Agent QA Scenarios.

- [x] 1. Vendor finreportparser + configs + path/numpy fix

  **What to do**:
  - 从 `/home/wh/Documents/finpdfpro/src/finreportparser/` 复制到 `src/finreportparser/`（排除 `__pycache__`）
  - 复制 `configs/default.yaml`, `configs/fast.yaml`, `configs/max_quality.yaml` 到仓库根 `configs/` 或与包约定一致的位置
  - 修复 `find_configs_dir()`：vendoring 后 `Path(__file__).parent...` 深度变化，确保 `load_config()` 找到 YAML
  - 放宽 vendored 包内对 `numpy<2` 的约束（注释/文档/任何硬编码上限）；确认 `np.array` 调用在 numpy 2.x 可用
  - 不复制 scripts/、output/、data/、.benchmarks/、smoke_output/、finpdfpro 测试与大体积产物
  - hatch 打包包含 `src/finreportparser`

  **Must NOT do**:
  - 不改成 path 依赖外部 finpdfpro
  - 不引入 paddle/torch 为 core 依赖

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Skills Evaluated but Omitted**: `customize-opencode` — 非 opencode 配置

  **Parallelization**:
  - **Can Run In Parallel**: NO（Wave 0 与 Task2/3 可部分并行，但本任务优先完成）
  - **Parallel Group**: Wave 0
  - **Blocks**: 2, 3, 11, 全部后续
  - **Blocked By**: None

  **References**:
  - Pattern: `/home/wh/Documents/finpdfpro/src/finreportparser/` — 完整源码
  - API: `/home/wh/Documents/finpdfpro/src/finreportparser/pipeline/orchestrator.py:parse_pdf` — 主入口
  - Config: `/home/wh/Documents/finpdfpro/src/finreportparser/config.py:find_configs_dir,load_config`
  - Configs: `/home/wh/Documents/finpdfpro/configs/*.yaml`
  - Target layout: `src/reproagent` 并列 `src/finreportparser`
  - WHY: config 路径与 numpy 是 Metis 标出的最高风险

  **Acceptance Criteria**:
  - [ ] `src/finreportparser/` 存在且可 import
  - [ ] `configs/` 中至少 default/fast/max_quality 可用
  - [ ] `uv run python -c "from finreportparser.config import load_config; c=load_config(); print(c.mode)"` 成功

  **QA Scenarios**:
  ```
  Scenario: load_config after vendor
    Tool: Bash
    Preconditions: Task1 完成且 uv sync 后
    Steps:
      1. uv run python -c "from finreportparser.config import load_config; c=load_config(); assert c is not None; print(getattr(c,'mode',c))"
    Expected Result: exit 0, 打印 mode（如 balanced）
    Failure Indicators: FileNotFoundError configs; ImportError
    Evidence: .sisyphus/evidence/task-1-load-config.txt

  Scenario: parse_pdf import path
    Tool: Bash
    Steps:
      1. uv run python -c "from finreportparser.pipeline.orchestrator import parse_pdf; print(parse_pdf.__name__)"
    Expected Result: prints parse_pdf
    Evidence: .sisyphus/evidence/task-1-import-parse.txt
  ```

  **Commit**: YES
  - Message: `feat(vendor): embed finreportparser and fix config path`
  - Files: `src/finreportparser/**`, `configs/**`, related packaging

- [x] 2. pyproject deps + hatch packages + .env.example

  **What to do**:
  - 更新 `pyproject.toml` core deps: 增加 `pymupdf`, `tqdm`, `pillow`, `httpx`, `pandas`（legacy_quant）
  - hatch packages: `reproagent` + `finreportparser`
  - optional extras: `ricequant=["rqdatac"]`, `qlib=["pyqlib"]`（或文档说明 git 源）, `paddle`, `vlm`, `formula`
  - 移除或标记废弃 `parser-marker` / `parser-llama` / `parser-mineru` 主路径（可留注释说明由 finpdfpro 替代）
  - 更新 `.env.example`: `PARSER_BACKEND=finpdfpro`, `FINPDFPRO_MODE`, `FINPDFPRO_VLM_BACKEND`, `DATA_SOURCE`, `QLIB_CN_DATA_PATH`, `LOCAL_DATA_PATH`, `RQ_*`
  - `uv lock` / `uv sync` 成功

  **Must NOT do**:
  - 不把 paddle/torch 放进 core
  - 不提交 `.env` 密钥

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task1 协作；依赖 Task1 包路径）
  - **Parallel Group**: Wave 0
  - **Blocks**: 全部
  - **Blocked By**: 1（至少包路径约定）

  **References**:
  - `pyproject.toml` 现有 extras
  - `/home/wh/Documents/finpdfpro/pyproject.toml` 依赖清单
  - `/home/wh/Documents/aiminer/.env.example` RQ/QLIB 变量
  - WHY: 依赖合并与 numpy 共存

  **Acceptance Criteria**:
  - [ ] `uv sync` exit 0
  - [ ] `uv run python -c "import fitz,pypdf,polars,numpy,pandas; print(numpy.__version__)"` exit 0

  **QA Scenarios**:
  ```
  Scenario: deps coexist
    Tool: Bash
    Steps:
      1. uv sync
      2. uv run python -c "import fitz,pypdf,polars,numpy,pandas; print('OK', numpy.__version__)"
    Expected Result: OK and numpy version printed
    Evidence: .sisyphus/evidence/task-2-deps.txt
  ```

  **Commit**: YES — `chore(deps): merge finreportparser and data backend extras`

- [x] 3. Settings 扩展（finpdfpro / qlib / local）

  **What to do**:
  - 修改 `src/reproagent/settings.py`:
    - `parser_backend` 默认 `finpdfpro`（Literal 含 finpdfpro；marker 等可保留 optional）
    - `finpdfpro_mode: Literal["fast","balanced","max-quality"] = "balanced"`
    - `finpdfpro_vlm_backend: Literal["none","paddle_vl","smolvlm","llamacpp_http"] = "none"`
    - `data_source: Literal["ricequant","qlib","local","tushare"]` — **加入 qlib**（保留 tushare 字段或映射到 local/文档废弃）
    - `qlib_data_path: Path | None`
    - `local_data_path: Path | None`
    - RQ 凭据字段对齐 aiminer（token/user/pass）若尚未有
  - 更新依赖 Settings 的测试/默认值

  **Must NOT do**:
  - 不破坏现有已通过的 settings 字段名（除非同步改测试）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0
  - **Blocks**: 12,15,18
  - **Blocked By**: None（可与 1 并行，字段先定义）

  **References**:
  - `src/reproagent/settings.py`
  - `masterplan.md` §4.1
  - aiminer `core/settings.py` 环境变量命名
  - WHY: 全链路配置入口

  **Acceptance Criteria**:
  - [ ] `get_settings().parser_backend == "finpdfpro"` 默认
  - [ ] 新字段可从环境变量读取

  **QA Scenarios**:
  ```
  Scenario: defaults
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.settings import Settings; s=Settings(); print(s.parser_backend, getattr(s,'finpdfpro_mode',None), s.data_source)"
    Expected Result: finpdfpro + balanced + 合法 data_source
    Evidence: .sisyphus/evidence/task-3-settings.txt
  ```

  **Commit**: YES — `feat(settings): finpdfpro and aiminer-like data backends`

- [x] 4. legacy_quant 旁路落地

  **What to do**:
  - 创建 `src/reproagent/legacy_quant/`
  - 复制 zip 内 `factor_db.py`, `factor_research_pipeline.py`, `factor_library_dashboard.py`（及可选 seed 逻辑）
  - 改为相对导入：`from .factor_db import FactorDB`
  - 提供 `__init__.py` 与可选 CLI 入口 `reproagent legacy-dashboard` 或 `python -m reproagent.legacy_quant...`（二选一，文档写清）
  - **禁止** core 业务强制依赖 legacy_quant

  **Must NOT do**:
  - 不把 pandas/sqlite 逻辑改写成 SQLModel（用户要求原样旁路）
  - 不让 pipeline 主路径硬依赖 legacy

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0
  - **Blocks**: 22
  - **Blocked By**: None

  **References**:
  - `/tmp/opencode/quant-agent-zip/量化agent/*` 或 `/home/wh/Documents/量化agent.zip`
  - README in zip
  - WHY: 用户明确旁路保留可运行原型

  **Acceptance Criteria**:
  - [ ] `uv run python -c "from reproagent.legacy_quant.factor_db import FactorDB; FactorDB"` 成功
  - [ ] 可运行 seed/dashboard 生成 HTML（路径写入 tmp 或 `~/.reproagent`）

  **QA Scenarios**:
  ```
  Scenario: import legacy
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.legacy_quant.factor_db import FactorDB; print(FactorDB)"
    Expected Result: class printed, exit 0
    Evidence: .sisyphus/evidence/task-4-legacy-import.txt

  Scenario: seed demo
    Tool: Bash
    Steps:
      1. uv run python -c "from pathlib import Path; from reproagent.legacy_quant.factor_db import FactorDB; p=Path('/tmp/legacy_factor.db'); db=FactorDB(p); db.seed_demo(); assert len(db.get_factors())>=1; db.close(); print(len(list(open(p,'rb'))))"
    Expected Result: factors seeded, db file non-empty
    Evidence: .sisyphus/evidence/task-4-seed.txt
  ```

  **Commit**: YES — `feat(legacy_quant): import quant agent zip as side module`

- [x] 5. 测试 fixtures：minimal PDF + OHLCV parquet

  **What to do**:
  - `tests/fixtures/sample_reports/minimal.pdf`：可用 pypdf/reportlab/pymupdf 生成最小合法 PDF（含少量中文/英文文本）
  - `tests/fixtures/test_data/prices.parquet`：合成 OHLCV（datetime, instrument/ts_code, open/high/low/close/volume）≥ 20 交易日 × ≥2 标的
  - 更新 `tests/conftest.py` fixtures 指向上述路径
  - 文档注明 e2e 使用 local backend + mock LLM

  **Must NOT do**:
  - 不提交真实研报 PDF / 敏感数据

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0
  - **Blocks**: 11,15,29
  - **Blocked By**: 2（工具依赖）

  **References**:
  - `tests/conftest.py`
  - aiminer `local_data.py` 列名规范
  - WHY: 离线 e2e 硬前置

  **Acceptance Criteria**:
  - [ ] fixtures 文件存在且可读
  - [ ] polars/pandas 可读 parquet；pypdf/fitz 可开 PDF

  **QA Scenarios**:
  ```
  Scenario: fixtures readable
    Tool: Bash
    Steps:
      1. uv run python -c "from pathlib import Path; import polars as pl; p=Path('tests/fixtures/test_data/prices.parquet'); assert p.exists(); df=pl.read_parquet(p); assert len(df)>0; print(df.columns)"
      2. uv run python -c "from pathlib import Path; p=Path('tests/fixtures/sample_reports/minimal.pdf'); assert p.exists() and p.stat().st_size>100; print(p.stat().st_size)"
    Expected Result: columns printed; pdf size >100
    Evidence: .sisyphus/evidence/task-5-fixtures.txt
  ```

  **Commit**: YES — `test(fixtures): minimal pdf and synthetic ohlcv`

- [ ] 6. 实现 utils/pdf.py

  **What to do**:
  - 用 `pypdf` 实现 `get_page_count`, `is_readable`, `has_pdf_header`
  - 对齐 masterplan / 现有函数签名

  **Must NOT do**: 不用 finreportparser 做页数检查（保持轻量）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**: YES | Wave 1 | Blocks: 10 | Blocked By: 2

  **References**:
  - `src/reproagent/utils/pdf.py`
  - `masterplan.md` utils 段
  - WHY: ingestion 校验基础

  **Acceptance Criteria**:
  - [ ] minimal.pdf 页数 ≥1；`has_pdf_header` True；`is_readable` True

  **QA Scenarios**:
  ```
  Scenario: page count on fixture
    Tool: Bash
    Steps:
      1. uv run python -c "from pathlib import Path; from reproagent.utils.pdf import get_page_count, is_readable, has_pdf_header; p=Path('tests/fixtures/sample_reports/minimal.pdf'); assert get_page_count(p)>=1; assert has_pdf_header(p); assert is_readable(p); print('pdf utils OK')"
    Expected Result: pdf utils OK
    Evidence: .sisyphus/evidence/task-6-pdf-utils.txt

  Scenario: invalid path
    Tool: Bash
    Steps:
      1. uv run python -c "from pathlib import Path; from reproagent.utils import pdf; 
try:
  pdf.get_page_count(Path('/tmp/no_such_file_xyz.pdf'))
  raise SystemExit('should fail')
except Exception as e:
  print(type(e).__name__)"
    Expected Result: 明确异常类型（非静默成功）
    Evidence: .sisyphus/evidence/task-6-pdf-missing.txt
  ```

  **Commit**: YES — `feat(utils): implement pdf helpers`

- [ ] 7. 实现 persistence repository + db 完善

  **What to do**:
  - 实现 `persistence/repository.py` 全部 CRUD：reports / library / reflection / review queue
  - 确保 `db.py` engine/session 可用；SQLite WAL 或 `check_same_thread=False` 按 masterplan
  - `AppPaths.ensure_layout()` 在启动路径被调用
  - 领域模型 ↔ table 映射与 `tables.py` 一致

  **Must NOT do**: 不改领域模型语义；不与 legacy_quant sqlite 混用同一文件

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**: YES | Wave 1 | Blocks: 10,21,23,24 | Blocked By: 2,3

  **References**:
  - `src/reproagent/persistence/{repository,tables,db,paths}.py`
  - `masterplan.md` §4.3
  - `src/reproagent/models/*`
  - WHY: 所有子系统持久化底座

  **Acceptance Criteria**:
  - [ ] save/get report by id 与 by hash 往返成功
  - [ ] library entry list 可过滤

  **QA Scenarios**:
  ```
  Scenario: report CRUD
    Tool: Bash
    Steps:
      1. uv run python -c "
from datetime import datetime, timezone
from pathlib import Path
from reproagent.persistence.repository import Repository
from reproagent.persistence.db import get_engine, init_db
from reproagent.models.report import ResearchReport
from reproagent.persistence.paths import AppPaths
# use tmp data dir if Settings allows override; else default
init_db()
repo = Repository()
r = ResearchReport(id='t-rep-1', file_path=Path('/tmp/a.pdf'), file_hash='h1', page_count=1, ingested_at=datetime.now(timezone.utc))
repo.save_report(r)
got = repo.get_report('t-rep-1')
assert got is not None and got.file_hash=='h1'
print('repo OK')
"
    Expected Result: repo OK
    Evidence: .sisyphus/evidence/task-7-repo.txt
  ```

  **Commit**: YES — `feat(persistence): implement repository CRUD`

- [ ] 8. 实现 cache_manager

  **What to do**:
  - 实现 `CacheManager.get_cached` / `get_cached_backtest` / `save`
  - 使用已实现 `cache_key.compute_cache_key`
  - 落盘 `~/.reproagent/cache/<key>/`（或 Settings data_dir）

  **Must NOT do**: 不缓存密钥

  **Recommended Agent Profile**: `quick` | Wave 1 | Blocks: 24 | Blocked By: 2

  **References**: `src/reproagent/cache/*`, masterplan §4.4

  **Acceptance Criteria**:
  - [ ] save 后 get 命中；错误 key 返回 None

  **QA Scenarios**:
  ```
  Scenario: cache roundtrip
    Tool: Bash
    Steps:
      1. uv run python -c "
from reproagent.cache.cache_manager import CacheManager
from reproagent.cache.cache_key import compute_cache_key
cm = CacheManager()
key = compute_cache_key if False else 'testkey123'
# call API as implemented; assert miss then hit
print('cache API import OK', CacheManager)
"
    Expected Result: import OK；实现后应有 miss/hit 断言
    Evidence: .sisyphus/evidence/task-8-cache.txt
  ```

  **Commit**: YES — `feat(cache): implement filesystem cache manager`

- [ ] 9. 实现 utils/plotting.py

  **What to do**:
  - matplotlib 实现 equity / group returns / IC timeseries 存 PNG
  - 签名对齐现有 stub

  **Must NOT do**: 不弹 GUI（Agg backend）

  **Recommended Agent Profile**: `quick` | Wave 1 | Blocks: 17,22 | Blocked By: 2

  **References**: `src/reproagent/utils/plotting.py`, zip dashboard 图表字段

  **Acceptance Criteria**:
  - [ ] 写出非空 PNG 文件

  **QA Scenarios**:
  ```
  Scenario: save equity chart
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from reproagent.utils.plotting import save_equity_curve_chart
# call with minimal series per signature
out = Path('/tmp/eq.png')
print('plotting module loaded')
"
    Expected Result: 实现后文件 size>0
    Evidence: .sisyphus/evidence/task-9-plot.txt
  ```

  **Commit**: YES — `feat(utils): matplotlib chart helpers`

- [ ] 10. 实现 ingestion（uploader / validator / review_queue）

  **What to do**:
  - `upload_pdf` → ResearchReport（hash via hashing.sha256_file）
  - `validate_pdf` 用 utils.pdf
  - review_queue enqueue/dequeue/confirm 走 Repository
  - invalid → 可入复核队列

  **Must NOT do**: 不在此阶段解析因子

  **Recommended Agent Profile**: `unspecified-high` | Wave 1 | Blocks: 24,26 | Blocked By: 6,7

  **References**: `src/reproagent/ingestion/*`, masterplan 子系统1, `utils/hashing.py`

  **Acceptance Criteria**:
  - [ ] ingest fixture PDF 得到 valid report 并可持久化

  **QA Scenarios**:
  ```
  Scenario: upload and validate fixture
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from reproagent.ingestion.uploader import upload_pdf
from reproagent.ingestion.validator import validate_pdf
p = Path('tests/fixtures/sample_reports/minimal.pdf')
rep = upload_pdf(p)
validate_pdf(rep)
assert rep.page_count >= 1
print('ingest OK', rep.id, rep.file_hash[:8])
"
    Expected Result: ingest OK + id + hash prefix
    Evidence: .sisyphus/evidence/task-10-ingest.txt

  Scenario: missing file
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from reproagent.ingestion.uploader import upload_pdf
try:
  upload_pdf(Path('/tmp/missing_reproagent.pdf'))
  raise SystemExit('expected error')
except Exception as e:
  print('ERR', type(e).__name__)
"
    Expected Result: ERR with exception name
    Evidence: .sisyphus/evidence/task-10-missing.txt
  ```

  **Commit**: YES — `feat(ingestion): upload validate review queue`

- [ ] 11. LayoutExtractor finpdfpro 适配

  **What to do**:
  - `LayoutExtractor(backend="finpdfpro")` 调用 `parse_pdf`
  - 将 `DocumentResult` 扁平化为 Markdown 字符串（text/table/heading/formula 等）
  - 捕获 CorruptPdfError → reproagent 异常
  - Settings 控制 mode/vlm
  - 其他 backend 可明确 NotImplemented 或移除主路径

  **Must NOT do**: 不实现 marker 主路径

  **Recommended Agent Profile**: `deep` | Wave 2 | Blocks: 14 | Blocked By: 1,2,3,5

  **References**:
  - `src/reproagent/parser/layout_extractor.py`
  - `finreportparser.pipeline.orchestrator.parse_pdf`
  - `finreportparser.types.DocumentResult`
  - `finreportparser.output.markdown`（若可复用写 md）
  - WHY: PDF 子系统唯一真实后端

  **Acceptance Criteria**:
  - [ ] extract(minimal.pdf report) 返回非空 str

  **QA Scenarios**:
  ```
  Scenario: extract markdown from fixture
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from datetime import datetime, timezone
from reproagent.parser.layout_extractor import LayoutExtractor
from reproagent.models.report import ResearchReport
from reproagent.utils.hashing import sha256_file
p=Path('tests/fixtures/sample_reports/minimal.pdf')
rep=ResearchReport(id='x', file_path=p, file_hash=sha256_file(p), page_count=1, ingested_at=datetime.now(timezone.utc))
md=LayoutExtractor(backend='finpdfpro').extract(rep)
assert isinstance(md,str) and len(md)>0
print('md_len', len(md))
"
    Expected Result: md_len > 0
    Evidence: .sisyphus/evidence/task-11-layout.txt

  Scenario: corrupt pdf handling
    Tool: Bash
    Steps:
      1. echo 'not a pdf' > /tmp/bad.pdf
      2. uv run python -c "
from pathlib import Path
from datetime import datetime, timezone
from reproagent.parser.layout_extractor import LayoutExtractor
from reproagent.models.report import ResearchReport
rep=ResearchReport(id='b', file_path=Path('/tmp/bad.pdf'), file_hash='0', page_count=0, ingested_at=datetime.now(timezone.utc))
try:
  LayoutExtractor(backend='finpdfpro').extract(rep)
  print('UNEXPECTED_OK')
except Exception as e:
  print('ERR', type(e).__name__)
"
    Expected Result: ERR ...（非 UNEXPECTED_OK）
    Evidence: .sisyphus/evidence/task-11-corrupt.txt
  ```

  **Commit**: YES — `feat(parser): finpdfpro layout extractor adapter`

- [ ] 12. LLMExtractor + mock fallback

  **What to do**:
  - 实现 `extract` / `revise`：OpenAI structured / Anthropic tool-use + Pydantic schema
  - **空 API key → 确定性 mock** `ParsedFactorSpec`（固定因子名/公式/指标）
  - 使用 `parser/prompts.py` Jinja 模板
  - 失败重试策略与 masterplan 附录 A 一致（可简化一次重试）

  **Must NOT do**: 测试依赖真实 key

  **Recommended Agent Profile**: `deep` | Wave 2 | Blocks: 13,14,23 | Blocked By: 3

  **References**: `parser/llm_extractor.py`, `models/factor_spec.py`, `parser/prompts.py`, masterplan 附录 A

  **Acceptance Criteria**:
  - [ ] 无 key 时 extract 返回 ≥1 个 spec 且字段合法

  **QA Scenarios**:
  ```
  Scenario: mock without keys
    Tool: Bash
    Steps:
      1. OPENAI_API_KEY= ANTHROPIC_API_KEY= LLM_API_KEY= uv run python -c "
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.settings import Settings
ex=LLMExtractor(Settings())
specs=ex.extract(None, '# mock md\\n因子: 动量\\n') if False else ex.extract  # call real signature
# Prefer: specs = ex.extract(report_or_md_per_signature)
print('llm extractor loaded', LLMExtractor)
"
    Expected Result: 实现后断言 len(specs)>=1 且 factor_name 非空
    Evidence: .sisyphus/evidence/task-12-llm-mock.txt
  ```

  **Commit**: YES — `feat(parser): llm extractor with mock fallback`

- [ ] 13. schema_validator + config_builder

  **What to do**:
  - SchemaValidator: [OK]/[WARN] 数据字典映射
  - ConfigBuilder: ParsedFactorSpec[] → ReplicationConfig + 可选 yaml 导出

  **Must NOT do**: 不静默丢弃全部字段

  **Recommended Agent Profile**: `unspecified-high` | Wave 2 | Blocks: 14 | Blocked By: 12

  **References**: `parser/schema_validator.py`, `parser/config_builder.py`, `models/replication.py`, masterplan 子系统2

  **Acceptance Criteria**:
  - [ ] mock specs 能 build 出合法 ReplicationConfig

  **QA Scenarios**:
  ```
  Scenario: build config from mock specs
    Tool: Bash
    Steps:
      1. uv run python -c "
from reproagent.parser.config_builder import ConfigBuilder
from reproagent.parser.schema_validator import SchemaValidator
print('modules', ConfigBuilder, SchemaValidator)
"
    Expected Result: 实现后 config 含 factor 与 backtest 参数
    Evidence: .sisyphus/evidence/task-13-config.txt
  ```

  **Commit**: YES — `feat(parser): validate specs and build replication config`

- [ ] 14. ReportParser 编排

  **What to do**:
  - `ReportParser.parse`: layout → llm → validate → config
  - 低置信/空因子 → 标记 review_required

  **Must NOT do**: 不在 parser 内做回测

  **Recommended Agent Profile**: `deep` | Wave 2 | Blocks: 24 | Blocked By: 11,12,13

  **References**: `parser/report_parser.py`, `parser/protocol.py`

  **Acceptance Criteria**:
  - [ ] 对 fixture report 返回 specs+config 结构

  **QA Scenarios**:
  ```
  Scenario: parse fixture offline
    Tool: Bash
    Steps:
      1. OPENAI_API_KEY= LLM_API_KEY= uv run python -c "
from pathlib import Path
from datetime import datetime, timezone
from reproagent.parser.report_parser import ReportParser
from reproagent.models.report import ResearchReport
from reproagent.utils.hashing import sha256_file
from reproagent.settings import Settings
p=Path('tests/fixtures/sample_reports/minimal.pdf')
rep=ResearchReport(id='p1', file_path=p, file_hash=sha256_file(p), page_count=1, ingested_at=datetime.now(timezone.utc))
out=ReportParser(Settings()).parse(rep)
print(type(out), out)
"
    Expected Result: 非 NotImplementedError；有可序列化输出
    Evidence: .sisyphus/evidence/task-14-report-parser.txt
  ```

  **Commit**: YES — `feat(parser): wire ReportParser orchestration`

- [ ] 15. data_loader：local / ricequant / qlib（lazy）

  **What to do**:
  - 实现 `DataLoader.load_price_data` / `load_fundamental_data`（基本面可最小 stub 或 local only）
  - **local**：移植 aiminer `local_data` 列别名与 OHLCV 校验；读 Settings.local_data_path / fixtures
  - **ricequant**：lazy import `rqdatac`；`RQ_TOKEN` 或 user/pass；失败清晰错误
  - **qlib**：lazy import；`qlib_data_path` / `QLIB_CN_DATA_PATH`
  - 默认测试路径：local + fixtures parquet
  - 输出优先 `polars.DataFrame`（可内部 pandas 再转换）

  **Must NOT do**:
  - 不强制安装 rqdatac/qlib
  - 不移植 aiminer swarm

  **Recommended Agent Profile**: `deep` | Wave 3 | Blocks: 18,19 | Blocked By: 3,5

  **References**:
  - `src/reproagent/reproducer/data_loader.py`
  - `/home/wh/Documents/aiminer/src/aiminer/core/local_data.py`
  - aiminer `evaluator_factory.py`, `rq_eval.fetch_data`, `modeltester`
  - WHY: 用户要求数据与 aiminer 一致

  **Acceptance Criteria**:
  - [ ] local 加载 fixtures parquet 行数 >0
  - [ ] 无 rqdatac 时 ricequant 路径给出明确 ImportError/配置错误信息

  **QA Scenarios**:
  ```
  Scenario: local load fixture
    Tool: Bash
    Steps:
      1. uv run python -c "
from datetime import date
from pathlib import Path
from reproagent.reproducer.data_loader import DataLoader
from reproagent.settings import Settings
s=Settings(data_source='local', local_data_path=Path('tests/fixtures/test_data'))
# adjust ctor to match implementation
dl=DataLoader(s)
df=dl.load_price_data('all', date(2018,1,1), date(2030,1,1))
assert len(df)>0
print('rows', len(df))
"
    Expected Result: rows > 0
    Evidence: .sisyphus/evidence/task-15-local.txt

  Scenario: ricequant missing dep message
    Tool: Bash
    Steps:
      1. uv run python -c "
from reproagent.settings import Settings
from reproagent.reproducer.data_loader import DataLoader
s=Settings(data_source='ricequant')
try:
  DataLoader(s).load_price_data('000001.XSHE', __import__('datetime').date(2020,1,1), __import__('datetime').date(2020,1,10))
except Exception as e:
  print('ERR', type(e).__name__, str(e)[:200])
"
    Expected Result: 清晰错误（缺依赖或缺凭证），非 traceback 黑洞
    Evidence: .sisyphus/evidence/task-15-rq-err.txt
  ```

  **Commit**: YES — `feat(reproducer): aiminer-like multi-backend data loader`

- [ ] 16. polars_engine 因子计算

  **What to do**:
  - 实现 `PolarsEngine.compute(FactorDefinition, data)`
  - 移植 aiminer `polars_engine` 核心算子子集：Ref/Delta/Mean/Std/Rank/CSRank/Corr/Ts_Rank/EMA 等
  - 支持表达式或 code 字段按 masterplan FactorDefinition

  **Must NOT do**: 不要求 Rust plugins

  **Recommended Agent Profile**: `deep` | Wave 3 | Blocks: 18,19 | Blocked By: 1-5

  **References**:
  - `src/reproagent/reproducer/polars_engine.py`
  - `/home/wh/Documents/aiminer/src/aiminer/core/alphaeval/polars_engine.py`
  - masterplan 附录 B
  - zip `PolarsEngine` 仅作最简参考（列选择 demo）

  **Acceptance Criteria**:
  - [ ] 对 fixture 数据计算简单因子（如 close 动量）得到等长序列

  **QA Scenarios**:
  ```
  Scenario: compute simple factor
    Tool: Bash
    Steps:
      1. uv run python -c "
import polars as pl
from reproagent.reproducer.polars_engine import PolarsEngine
# load fixture and compute per API
print('engine', PolarsEngine)
"
    Expected Result: 实现后 factor 列非全 null
    Evidence: .sisyphus/evidence/task-16-polars.txt
  ```

  **Commit**: YES — `feat(reproducer): polars factor engine`

- [ ] 17. metrics + StrategyBacktester

  **What to do**:
  - `metrics`: IC, group returns, sharpe, max_drawdown, generate_charts
  - `StrategyBacktester.run`: 分组多空 / 分位数回测
  - 可参考 zip 的 IC/分组逻辑，但输出对齐 Pydantic `BacktestResult`

  **Must NOT do**: 不实现 alpha-lens DSR/PBO

  **Recommended Agent Profile**: `unspecified-high` | Wave 3 | Blocks: 19 | Blocked By: 9

  **References**: `reproducer/metrics.py`, `reproducer/backtester.py`, zip `factor_research_pipeline.py`, masterplan 子系统3

  **Acceptance Criteria**:
  - [ ] 合成因子序列上 IC 为有限 float；mdd ≤0

  **QA Scenarios**:
  ```
  Scenario: metrics finite
    Tool: Bash
    Steps:
      1. uv run python -c "
import numpy as np
from reproagent.reproducer import metrics
print('metrics', metrics)
"
    Expected Result: compute_ic 等可调用且返回 finite
    Evidence: .sisyphus/evidence/task-17-metrics.txt
  ```

  **Commit**: YES — `feat(reproducer): metrics and group backtester`

- [ ] 18. evaluator_factory + RiceQuantEval 薄封装

  **What to do**:
  - 完善 `evaluator_factory.build_evaluator`：按 Settings/data_source 分发 polars / ricequant / qlib / local 评估器
  - `rqalpha_engine.RiceQuantEval`：数据获取 + 评估指标薄封装（不必完整 rqalpha 策略引擎）
  - 与 Task15/16 对齐

  **Must NOT do**: 不实现完整 rqalpha run_func 策略框架（Metis 锁定）

  **Recommended Agent Profile**: `deep` | Wave 3 | Blocks: 19 | Blocked By: 15,16

  **References**: `evaluator_factory.py`, `rqalpha_engine.py`, aiminer `evaluator_factory.py` / `rq_eval.py`

  **Acceptance Criteria**:
  - [ ] local 配置下 build_evaluator 返回可 compute 对象

  **QA Scenarios**:
  ```
  Scenario: build local evaluator
    Tool: Bash
    Steps:
      1. uv run python -c "
from reproagent.reproducer.evaluator_factory import build_evaluator
from reproagent.settings import Settings
print(build_evaluator)
"
    Expected Result: 实现后 local evaluator.compute 可跑 fixture
    Evidence: .sisyphus/evidence/task-18-factory.txt
  ```

  **Commit**: YES — `feat(reproducer): evaluator factory and thin RQ eval`

- [ ] 19. FactorReproducer 编排

  **What to do**:
  - `reproduce` / `compute_factor` / `_build_factor_def`
  - 串联 data_loader → engine → backtester → metrics → BacktestResult（含 parquet 路径）

  **Must NOT do**: 不做偏差分析（交给 deviation）

  **Recommended Agent Profile**: `deep` | Wave 3 | Blocks: 20,24 | Blocked By: 15-18

  **References**: `reproducer/reproducer.py`, masterplan 子系统3

  **Acceptance Criteria**:
  - [ ] 给定 mock ReplicationConfig + local data 产出 BacktestResult

  **QA Scenarios**:
  ```
  Scenario: reproduce with mock config
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.reproducer.reproducer import FactorReproducer; print(FactorReproducer)"
    Expected Result: 实现后 BacktestResult 字段完整
    Evidence: .sisyphus/evidence/task-19-reproducer.txt
  ```

  **Commit**: YES — `feat(reproducer): FactorReproducer orchestration`

- [ ] 20. DeviationAnalyzer + root_cause

  **What to do**:
  - `analyze` 对比 BacktestResult vs ReportedMetrics + ToleranceConfig
  - `should_reflect` 决策
  - `classify_root_cause` 枚举
  - 可参考 zip DeviationAnalyzer/Controller 的 case 分类思路，但接口以 masterplan 为准

  **Must NOT do**: 不做 DSR/PBO

  **Recommended Agent Profile**: `unspecified-high` | Wave 4 | Blocks: 23,24 | Blocked By: 19

  **References**: `deviation/*`, `models/deviation.py`, zip deviation 类, masterplan 子系统4

  **Acceptance Criteria**:
  - [ ] 偏差在容忍内 → passed True；超限 → False + root_cause

  **QA Scenarios**:
  ```
  Scenario: tolerance pass/fail
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.deviation.analyzer import DeviationAnalyzer; from reproagent.deviation.root_cause import classify_root_cause; print(DeviationAnalyzer, classify_root_cause)"
    Expected Result: 实现后两条路径断言
    Evidence: .sisyphus/evidence/task-20-deviation.txt
  ```

  **Commit**: YES — `feat(deviation): analyzer and root cause`

- [ ] 21. library manager + classifier + index/wiki writers

  **What to do**:
  - FactorLibraryManager register/get/list/dedup_check/update_index/update_wiki
  - StyleClassifier 规则优先 + LLM fallback（无 key 用规则）
  - IndexWriter / WikiWriter 写 `AppPaths` 下 markdown
  - 使用已实现 versioning.compute_dedup_hash / bump

  **Must NOT do**: 不混用 legacy_quant.sqlite 作为主库

  **Recommended Agent Profile**: `unspecified-high` | Wave 4 | Blocks: 22,24 | Blocked By: 7

  **References**: `library/*`, masterplan 子系统5, `library/versioning.py`

  **Acceptance Criteria**:
  - [ ] register 后 list 可见；重复 dedup 版本 bump 或拒绝策略符合 masterplan

  **QA Scenarios**:
  ```
  Scenario: register and list
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.library.manager import FactorLibraryManager; print(FactorLibraryManager)"
    Expected Result: 实现后 register/list 往返
    Evidence: .sisyphus/evidence/task-21-library.txt
  ```

  **Commit**: YES — `feat(library): manager classifier index wiki`

- [ ] 22. HTML 因子库仪表盘（from zip）

  **What to do**:
  - 新增 `library/dashboard.py`：`generate_html_dashboard(factors, output_path) → Path`
  - 移植 zip `factor_library_dashboard.py` Chart.js 深色 UI
  - 数据可从 SQLModel library 或传入 dict 列表
  - CLI `library --html` 或默认生成到 `~/.reproagent/wiki/factor_library.html`

  **Must NOT do**: 不建 Flask/FastAPI 服务

  **Recommended Agent Profile**: `visual-engineering` 或 `unspecified-high` | Wave 4 | Blocks: 26 | Blocked By: 4,21

  **References**: zip `factor_library_dashboard.py`, Chart.js CDN 用法

  **Acceptance Criteria**:
  - [ ] 输出 HTML size > 1KB 且含 `chart.js` 或 Chart 关键字

  **QA Scenarios**:
  ```
  Scenario: generate html
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from reproagent.library.dashboard import generate_html_dashboard
factors=[{'name':'动量因子','ic_series':[0.01,0.02],'excess_cum':[100,101],'stats':{'ic':0.02,'icir':0.5,'ann_return':5.0,'max_drawdown':-2.0,'win_rate':55,'std':0.04}}]
out=generate_html_dashboard(factors, Path('/tmp/factor_library.html'))
assert out.exists() and out.stat().st_size>1000
text=out.read_text(encoding='utf-8')
assert 'Chart' in text or 'chart' in text
print('html', out.stat().st_size)
"
    Expected Result: html size printed >1000
    Evidence: .sisyphus/evidence/task-22-html.txt
  ```

  **Commit**: YES — `feat(library): chart.js html dashboard`

- [ ] 23. ReflectionLoopController

  **What to do**:
  - N≤3 有界循环；持久化 ReflectionState/Step
  - 防震荡：分数不改善 streak
  - 调用 LLMExtractor.revise + reproducer + analyzer
  - 收敛入库信号 / 耗尽进人工复核

  **Must NOT do**: 无限循环；不依赖真实 LLM（mock 可强制耗尽或收敛）

  **Recommended Agent Profile**: `deep` | Wave 5 | Blocks: 24 | Blocked By: 12,20,7

  **References**: `deviation/reflection_loop.py`, `models/reflection.py`, masterplan 子系统4, AgentQuant 范式

  **Acceptance Criteria**:
  - [ ] `current_iteration <= 3`；status ∈ {converged, exhausted, escalated, ... 文档定义}

  **QA Scenarios**:
  ```
  Scenario: bounded loop
    Tool: Bash
    Steps:
      1. OPENAI_API_KEY= uv run python -c "from reproagent.deviation.reflection_loop import ReflectionLoopController; print(ReflectionLoopController)"
    Expected Result: run 后 iteration≤3
    Evidence: .sisyphus/evidence/task-23-reflection.txt
  ```

  **Commit**: YES — `feat(deviation): reflection loop controller`

- [ ] 24. pipeline.reproduce_report 端到端

  **What to do**:
  - 按 `pipeline.py` 注释步骤实现：ingest → cache → parse → reproduce → deviation → register / reflect / review → notify
  - 空 markdown / 空因子 → review queue
  - 日志用 loguru

  **Must NOT do**: 不吞掉所有异常

  **Recommended Agent Profile**: `deep` | Wave 5 | Blocks: 26,27,29 | Blocked By: 8,10,14,19,20,21,23

  **References**: `src/reproagent/pipeline.py`, masterplan §9

  **Acceptance Criteria**:
  - [ ] mock+local+fixture 整链跑完不抛未捕获异常

  **QA Scenarios**:
  ```
  Scenario: e2e offline pipeline
    Tool: Bash
    Steps:
      1. OPENAI_API_KEY= ANTHROPIC_API_KEY= LLM_API_KEY= uv run python -c "
from pathlib import Path
from reproagent.pipeline import reproduce_report
from reproagent.settings import Settings
from pathlib import Path as P
s=Settings(data_source='local', local_data_path=P('tests/fixtures/test_data'))
reproduce_report(Path('tests/fixtures/sample_reports/minimal.pdf'), s)
print('pipeline OK')
"
    Expected Result: pipeline OK
    Evidence: .sisyphus/evidence/task-24-pipeline.txt

  Scenario: missing pdf
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
from reproagent.pipeline import reproduce_report
from reproagent.settings import Settings
try:
  reproduce_report(Path('/tmp/nope.pdf'), Settings())
  print('UNEXPECTED')
except Exception as e:
  print('ERR', type(e).__name__)
"
    Expected Result: ERR ...
    Evidence: .sisyphus/evidence/task-24-missing.txt
  ```

  **Commit**: YES — `feat(pipeline): end-to-end reproduce_report`

- [ ] 25. logging_setup 完善

  **What to do**:
  - 若仍为桩/空：配置 loguru 控制台 + `data_dir/logs` 轮转
  - CLI/pipeline 启动时调用

  **Must NOT do**: 不日志打印 API key

  **Recommended Agent Profile**: `quick` | Wave 5 | Blocks: 26 | Blocked By: 2,3

  **References**: `logging_setup.py`, masterplan §4.2

  **Acceptance Criteria**:
  - [ ] 调用后 loguru 写出至少一条日志文件或可控 console

  **QA Scenarios**:
  ```
  Scenario: setup logging
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.logging_setup import setup_logging; setup_logging(); from loguru import logger; logger.info('hello'); print('log OK')"
    Expected Result: log OK
    Evidence: .sisyphus/evidence/task-25-log.txt
  ```

  **Commit**: YES — `feat(logging): loguru setup`

- [ ] 26. CLI 全命令接线

  **What to do**:
  - `ingest` / `reproduce` / `library` / `review` 去掉 stub exit1，接真实实现
  - 可选 `legacy-dashboard` 或 `library --html`
  - Rich 输出成功/失败信息
  - `tui` 保持

  **Must NOT do**: 不在 CLI 塞业务大段逻辑（应调 pipeline/manager）

  **Recommended Agent Profile**: `unspecified-high` | Wave 6 | Blocks: 29 | Blocked By: 24

  **References**: `cli.py`, masterplan §5

  **Acceptance Criteria**:
  - [ ] `reproagent --help` 列出命令；ingest/reproduce 对 fixture 非 stub 失败

  **QA Scenarios**:
  ```
  Scenario: help and ingest
    Tool: Bash
    Steps:
      1. uv run reproagent --help
      2. OPENAI_API_KEY= uv run reproagent ingest tests/fixtures/sample_reports/minimal.pdf
    Expected Result: help 含 reproduce；ingest 成功信息（非 [stub]）
    Evidence: .sisyphus/evidence/task-26-cli.txt

  Scenario: library command
    Tool: Bash
    Steps:
      1. uv run reproagent library
    Expected Result: exit 0（可为空列表）
    Evidence: .sisyphus/evidence/task-26-library.txt
  ```

  **Commit**: YES — `feat(cli): wire real commands`

- [ ] 27. 完整 Textual TUI 三屏 + widgets

  **What to do**:
  - 实现 `screens/reproduction.py`, `library_browser.py`, `review.py`
  - 接线 widgets：factor_tree, deviation_gauge, log_panel
  - 同步域逻辑用 `anyio.to_thread.run_sync` 或等价
  - 保持可启动；提供 Textual 测试 harness 冒烟

  **Must NOT do**: 不做复杂拖拽/实时流花活（Metis 锁定最小可用完整三屏）

  **Recommended Agent Profile**: `visual-engineering` | Wave 6 | Blocks: 29 | Blocked By: 24

  **References**: `tui/**`, masterplan 子系统6, Textual docs

  **Acceptance Criteria**:
  - [ ] `reproagent tui` 可启动；三屏类存在且 compose 无 placeholder-only

  **QA Scenarios**:
  ```
  Scenario: tui import and app construct
    Tool: Bash
    Steps:
      1. uv run python -c "from reproagent.tui.app import ReproAgentApp; app=ReproAgentApp(); print(type(app).__name__)"
    Expected Result: ReproAgentApp
    Evidence: .sisyphus/evidence/task-27-tui.txt

  Scenario: screens not pure TODO
    Tool: Bash
    Steps:
      1. uv run python -c "
from pathlib import Path
for name in ['reproduction','library_browser','review']:
  p=Path(f'src/reproagent/tui/screens/{name}.py')
  t=p.read_text(encoding='utf-8')
  assert 'TODO: ' not in t or 'placeholder' not in t.lower()
print('screens ok')
"
    Expected Result: screens ok（实现后去掉占位文案）
    Evidence: .sisyphus/evidence/task-27-screens.txt
  ```

  **Commit**: YES — `feat(tui): full screens and widgets`

- [ ] 28. 子系统单测补齐（tests-after）

  **What to do**:
  - 为 parser/reproducer/deviation/library/persistence 增加 unit tests（mock LLM/data）
  - 不依赖真实网络/凭证
  - 保持 `tests/unit/test_models.py` 通过

  **Must NOT do**: 不写 flaky 真实 API 测试

  **Recommended Agent Profile**: `unspecified-high` | Wave 7 | Blocks: 29 | Blocked By: 6-23

  **References**: 现有 `tests/unit/test_models.py`, pytest 配置

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/unit -q` 全绿

  **QA Scenarios**:
  ```
  Scenario: unit tests
    Tool: Bash
    Steps:
      1. uv run pytest tests/unit -q
    Expected Result: exit 0
    Evidence: .sisyphus/evidence/task-28-unit.txt
  ```

  **Commit**: YES — `test: unit coverage for subsystems`

- [ ] 29. e2e 测试启用 + conformance 策略

  **What to do**:
  - 实现/取消 skip `tests/integration/test_e2e.py`：mock LLM + local data
  - `tests/conformance/test_engine_parity.py`：若双引擎未齐，**保持 skip 并写明原因**（Metis：parity 可延后）

  **Must NOT do**: 不在 CI 强制 rqdatac

  **Recommended Agent Profile**: `unspecified-high` | Wave 7 | Blocks: FINAL | Blocked By: 24,28

  **References**: `tests/integration/test_e2e.py`, `tests/conformance/test_engine_parity.py`

  **Acceptance Criteria**:
  - [ ] e2e 测试通过；parity 有明确 skip 理由或通过

  **QA Scenarios**:
  ```
  Scenario: e2e pytest
    Tool: Bash
    Steps:
      1. OPENAI_API_KEY= uv run pytest tests/integration/test_e2e.py -q
    Expected Result: passed（非 skip 除非文档化）
    Evidence: .sisyphus/evidence/task-29-e2e.txt
  ```

  **Commit**: YES — `test: enable offline e2e pipeline`

- [ ] 30. README / masterplan 入口说明更新

  **What to do**:
  - 更新 README：finpdfpro vendor、数据后端 aiminer 模式、legacy_quant、CLI 示例、extras 安装
  - 注明默认 `PARSER_BACKEND=finpdfpro`
  - 不写密钥

  **Must NOT do**: 不删除 masterplan.md

  **Recommended Agent Profile**: `writing` | Wave 7 | Blocks: FINAL | Blocked By: 2,26

  **References**: `README.md`, `.env.example`

  **Acceptance Criteria**:
  - [ ] README 含 finreportparser、local/ricequant/qlib、legacy_quant 说明

  **QA Scenarios**:
  ```
  Scenario: readme keywords
    Tool: Bash
    Steps:
      1. rg -n "finreportparser|finpdfpro|legacy_quant|qlib|ricequant" README.md
    Expected Result: 至少 3 处命中关键主题
    Evidence: .sisyphus/evidence/task-30-readme.txt
  ```

  **Commit**: YES — `docs: update README for merge and backends`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  对照 Must Have / Must NOT Have；检查 evidence；`VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  `uv run ruff check src tests`；`uv run pytest -q`；扫 `NotImplementedError` 残留与 AI slop

- [ ] F3. **Real Manual QA** — `unspecified-high`
  执行全部关键 CLI/python -c 场景；证据写入 `.sisyphus/evidence/final-qa/`

- [ ] F4. **Scope Fidelity Check** — `deep`
  确认未引入 aiminer swarm/RAG；未做 alpha-lens 进阶；vendor 未拷 scripts/output

---

## Commit Strategy

- 按波次原子提交: `feat(vendor): ...` / `feat(parser): ...` / `feat(reproducer): ...` / `feat(pipeline): ...` / `test: ...`
- 禁止提交密钥、大体积 output/、`.venv`

---

## Success Criteria

### Verification Commands
```bash
uv sync
uv run python -c "from finreportparser.config import load_config; load_config(); import fitz, pypdf, polars, numpy; print('deps OK')"
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
uv run reproagent --help
```

### Final Checklist
- [ ] 全量 masterplan 业务可跑通（mock + local）
- [ ] PDF 仅经 finreportparser
- [ ] legacy_quant 可独立演示
- [ ] HTML + TUI + CLI 可用
- [ ] 无真实凭证依赖的测试全绿
