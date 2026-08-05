# ReproAgent

> 卖方研报 → AI 解析 → 因子复现 → 偏差自愈 → 因子库

ReproAgent 是一个面向中国 A 股市场的量化研报因子自动复现系统。
上传 PDF 卖方研报，自动提取因子定义、计算因子值、回测验证、偏差诊断与自愈修复，最终沉淀为结构化因子库。

## 快速开始

```bash
# 安装
git clone <repo-url> && cd reproagent
uv sync --extra dev

# 离线体验（无需 LLM API Key）
OPENAI_API_KEY= ANTHROPIC_API_KEY= DATA_SOURCE=local \
  uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf

# 生产模式
cp .env.example .env   # 填入 LLM_API_KEY
APP_ENV=prod uv run reproagent reproduce report.pdf

# 浏览因子库
uv run reproagent library --html

# 启动 TUI
uv run reproagent tui
```

## 系统架构

```
                    ┌─────────────┐
   PDF 研报 ──────→ │  Ingestion  │ 上传 / 校验 / 复核队列
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │   Parser    │ finreportparser 布局提取
                    │             │ LLM 结构化因子抽取
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │ Reproducer  │ Polars 因子计算 (55+ 算子)
                    │             │ 分组回测 + IC + 反过拟合
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │  Deviation  │ 偏差对比 / 根因分类
                    │             │ 反思循环 (≤3 次自愈)
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │   Library   │ 去重入库 / 分类 / 版本化
                    │             │ 经验记忆 / 衰减监控
                    └─────────────┘
```

## 核心特性

- **多后端 PDF 解析** — finreportparser (默认): 布局提取、表格修复、图表识别
- **LLM 结构化提取** — OpenAI / Anthropic 视觉模型 + Pydantic Schema 约束输出
- **55+ 因子算子** — Qlib 兼容表达式: Rank, CSZScore, Ref, Mean, Std, EMA, WMA, Ts_Rank, Corr, Cov 等
- **因子引擎正确性** — AST 求值器 + 确定性参考值 CI 自检
- **反过拟合套件** — DSR, PBO, MinBTL, Bootstrap Sharpe CI, Walk-Forward, 安慰剂检验, 子样本压力测试
- **数据口径守卫** — ST/停牌/新股/涨跌停自动过滤, 未来函数 AST 检测
- **反思自愈循环** — N≤3 有界迭代, 防震荡, 跨报告经验记忆
- **CLI + TUI + MCP** — Typer 命令行, Textual 终端界面, FastMCP 8 工具 AI Agent 调用
- **多数据源** — local (Parquet/CSV), RiceQuant, Tushare, Qlib
- **全离线可跑** — 无 LLM/API 时可使用确定性 Mock 因子, 无需联网

## CLI 命令

```bash
reproagent ingest report.pdf           # 摄入研报
reproagent reproduce report.pdf        # 端到端复现
reproagent library                     # 列出因子库
reproagent library --html              # 生成 HTML 仪表盘
reproagent review --list               # 查看复核队列
reproagent review --approve <id>       # 批准
reproagent benchmark --list            # 基准语料列表
reproagent benchmark --run <id>        # 运行基准验证
reproagent mcp                         # 启动 MCP 服务器
reproagent tui                         # 启动 TUI
```

## 配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `APP_ENV` | `dev` 允许 mock LLM / `prod` 禁止 | `dev` |
| `LLM_API_KEY` | LLM API Key（dev 可选，prod 必须） | — |
| `LLM_PROVIDER` | `openai` 或 `anthropic` | `openai` |
| `LLM_MODEL` | 模型名 | `gpt-4o` |
| `PARSER_BACKEND` | PDF 后端 | `finpdfpro` |
| `DATA_SOURCE` | `local` / `ricequant` / `tushare` / `qlib` | `local` |
| `LOCAL_DATA_PATH` | 本地数据目录 | `tests/fixtures/test_data` |

详见 `.env.example` 和 `src/reproagent/settings.py`。

## 安装选项

```bash
uv sync --extra dev          # 开发工具
uv sync --extra instructor   # LLM 结构化提取
uv sync --extra ricequant    # 米筐数据后端
uv sync --extra tushare      # Tushare 数据后端
uv sync --extra paddle       # PaddleOCR
uv sync --extra vlm          # 本地 VLM (transformers+torch)
```

## 测试

```bash
make test                    # 全量测试
make lint                    # Ruff 检查
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q  # 离线测试
```

166 个测试, 0 skip, ~3.5s 完成。

## 项目结构

```
src/
  reproagent/
    models/          # Pydantic 领域模型 (10 文件)
    ingestion/       # 研报摄入、校验、复核队列
    parser/          # finpdfpro 布局 + LLM 结构化提取 + schema 校验
    reproducer/      # 因子计算 (55+ 算子) + 回测 + 反过拟合 + 数据守卫
    deviation/       # 偏差分析 + 根因分类 + 反思循环
    library/         # 因子库管理 + 经验记忆 + 衰减监控
    persistence/     # SQLModel 持久化
    cache/           # 文件系统缓存
    tui/             # Textual 终端界面
    agents/          # Multi-Agent 研究框架骨架
    cli.py           # Typer CLI (8 命令)
    pipeline.py      # 端到端编排
    mcp_server.py    # FastMCP 服务器 (8 工具)
    settings.py      # pydantic-settings 配置
  finreportparser/   # Vendored PDF 布局解析后端
tests/
  conformance/       # 引擎正确性 + 引擎校验 + 基准语料
  integration/       # E2E 管线
  unit/              # 单元测试 (17 文件)
  fixtures/          # 测试数据 + benchmark 语料 + 引擎验证参考值
configs/             # finreportparser YAML 配置
```

## 技术栈

| 层 | 选型 |
|---|------|
| 语言 | Python 3.12+ |
| 包管理 | uv + pyproject.toml |
| 数据模型 | Pydantic v2 |
| 因子计算 | Polars (lazy API) |
| 持久化 | SQLite via SQLModel |
| LLM | OpenAI / Anthropic via instructor |
| CLI | Typer + Rich |
| TUI | Textual |
| MCP | FastMCP |
| 测试 | pytest |

## License

MIT
