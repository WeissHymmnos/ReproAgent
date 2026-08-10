# ReproAgent 1.0

> 卖方研报 → AI 解析 → 因子复现 → 偏差自愈 → 因子库

ReproAgent 是面向中国 A 股 / 转债市场的量化研报因子自动复现系统。
上传 PDF 卖方研报（或已解析 Markdown），自动提取因子定义、计算因子值、回测验证、偏差诊断与自愈修复，最终沉淀为结构化因子库。

## 快速开始

```bash
# 安装
git clone <repo-url> && cd reproagent
uv sync --extra dev

# 离线体验（无需 LLM API Key）
OPENAI_API_KEY= ANTHROPIC_API_KEY= DATA_SOURCE=local \
  LOCAL_DATA_PATH=tests/fixtures/test_data \
  uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf

# 基准全链路（ground_truth，不依赖 LLM）
DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
  uv run reproagent benchmark --run minimal

DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
  uv run reproagent benchmark --run cb-factor-investing

# 从 Markdown 复现（跳过 PDF）
uv run reproagent text -f 转债量化手册_因子投资实践_v2.md -b 华泰证券

# 生产模式（需 LLM）
cp .env.example .env   # 填入 LLM_API_KEY
APP_ENV=prod DATA_SOURCE=tushare uv run reproagent reproduce report.pdf

# 浏览因子库 / TUI / MCP
uv run reproagent library --html
uv run reproagent tui
uv run reproagent mcp

# 浏览器工作台（因子库 / 人工复核 / 研报复现）
uv run reproagent serve --port 8765
# 打开 http://127.0.0.1:8765/
```

## 系统架构

```
                    ┌─────────────┐
   PDF / Markdown ─→│  Ingestion  │ 上传 / 校验 / 复核队列
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │   Parser    │ finreportparser 布局
                    │             │ 分块 LLM 提取 + 置信度门控
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │ Reproducer  │ Polars 55+ 算子 + 守卫
                    │             │ 分组回测 + 反过拟合
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │  Deviation  │ 偏差 / 根因 / ≤3 次自愈
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │   Library   │ 入库 / wiki / 经验记忆
                    └─────────────┘
```

## 核心特性

- **多后端 PDF 解析** — finreportparser：布局、表格修复、图表识别
- **长文分块 LLM 提取** — 按页/长度切分，合并去重
- **置信度门控** — 低置信 / WARN 映射默认进人工复核
- **55+ 因子算子** — Rank, CSZScore, Ref, Mean, Std, EMA, Corr 等
- **转债字段** — ytm / premium_rate / bond_value / implied_vol / option_value …
- **反过拟合** — DSR, PBO, MinBTL, Bootstrap CI, Walk-Forward, Placebo
- **数据守卫** — ST/停牌/新股/涨跌停；未来函数 AST 检测
- **反思自愈** — N≤3 + 按根因修订 + ExperienceMemory
- **Benchmark** — ground_truth 驱动全链路比对（`minimal` / `cb-factor-investing`）
- **CLI + TUI + MCP** — Typer / Textual / FastMCP 8 工具
- **全离线可跑** — mock LLM + local parquet

## CLI

```bash
reproagent ingest report.pdf
reproagent reproduce report.pdf
reproagent text -f report.md [-t title] [-b broker]
reproagent library [--html] [-s style]
reproagent review --list | --approve ID | --reject ID
reproagent serve [--host 127.0.0.1] [--port 8765]
reproagent benchmark --list | --run ID | --run-all | --report
reproagent mcp
reproagent tui
reproagent --version
```

### 统一输出 schema（reproduce / text）

```json
{
  "status": "passed|partial|review_enqueued|...",
  "source": "pdf|text",
  "report_id": "...",
  "factor_count": 1,
  "summary": {"total": 1, "passed": 1, "converged": 0, "review_enqueued": 0, "errors": 0},
  "factors": [{"factor_name": "...", "status": "passed", "metrics": {...}}]
}
```

## 配置

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `APP_ENV` | `dev` 允许 mock / `prod` 禁止 | `dev` |
| `LLM_API_KEY` | LLM Key（prod 必须） | — |
| `LLM_PROVIDER` | `openai` / `anthropic` | `anthropic` |
| `LLM_MODEL` | 模型名 | `claude-sonnet-4-5` |
| `PARSER_BACKEND` | PDF 后端 | `finpdfpro` |
| `DATA_SOURCE` | `local` / `ricequant` / `tushare` / `qlib` | `local` |
| `LOCAL_DATA_PATH` | 本地 panel 目录 | `tests/fixtures/test_data` |

详见 `.env.example` 与 `src/reproagent/settings.py`。

### 数据源运行手册

| 源 | 准备 | 用途 |
|----|------|------|
| **local** | `prices.parquet` + 可选 `fundamentals.parquet` / `cb_prices.parquet` | CI / 离线 / 转债 fixture |
| **tushare** | `TUSHARE_TOKEN` + `uv sync --extra tushare` | 日常股票/基本面 |
| **ricequant** | `RICEQUANT_TOKEN` 或 `RQ_USER`/`RQ_PASS` + extra | 机构级量价 |
| **qlib** | `QLIB_DATA_PATH` | 研究用本地 qlib 库 |

转债 universe 别名：`全转债` / `cb` / `convertible` → 优先读 `cb_prices.parquet`。

### 生产检查清单

1. `APP_ENV=prod` + 有效 `LLM_API_KEY`
2. `DATA_SOURCE` 非 local 时凭证齐全
3. 关闭 mock：不要设 `ALLOW_MOCK_LLM=true`
4. 跑 `benchmark --run minimal` 冒烟
5. 长研报建议 `FINPDFPRO_MODE=balanced` 或 `max-quality`

## 安装选项

```bash
uv sync --extra dev          # 开发
uv sync --extra instructor   # LLM 结构化提取
uv sync --extra ricequant    # 米筐
uv sync --extra tushare      # Tushare
uv sync --extra paddle       # PaddleOCR
uv sync --extra vlm          # 本地 VLM
```

## 测试

```bash
make test
make lint
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
```

## 项目结构

```
src/
  reproagent/
    models/ parser/ reproducer/ deviation/ library/
    benchmark/       # ground_truth 全链路 runner
    pipeline.py      # 端到端编排
    cli.py mcp_server.py tui/
  finreportparser/   # Vendored PDF 后端
tests/
  conformance/ unit/ integration/ fixtures/
```

## 技术栈

| 层 | 选型 |
|---|------|
| 语言 | Python 3.12+ |
| 包管理 | uv + pyproject.toml |
| 因子计算 | Polars |
| 持久化 | SQLite (SQLModel) + Parquet |
| LLM | OpenAI / Anthropic + instructor |
| CLI / TUI / MCP | Typer · Textual · FastMCP |

## License

MIT
