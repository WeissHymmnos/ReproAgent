# ReproAgent

研报因子自动复现系统：上传 PDF 卖方研报 → 解析因子定义 → 回测复现 → 偏差自愈 → 入因子库。

PDF 布局解析由 vendored 的 [`finreportparser`](./src/finreportparser)（源自 finpdfpro）提供，作为唯一主 PDF 后端；
非 PDF 逻辑按 [masterplan.md](./masterplan.md) 实现，数据后端对齐 aiminer（`local` / `ricequant` / `qlib`），
并保留 `量化agent.zip` 原样旁路于 `legacy_quant`。

## 要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）

## 安装

```bash
uv sync --extra dev
cp .env.example .env   # 填入 LLM_API_KEY 等（离线 mock 可留空）
```

可选 extras：

| extra | 说明 |
|-------|------|
| `ricequant` | 安装 `rqdatac`，启用 ricequant 数据后端 |
| `qlib` | qlib 数据后端（需自行安装 `pyqlib`） |
| `rqalpha` | rqalpha 评估引擎薄封装 |
| `instructor` | LLM 结构化提取（OpenAI / Anthropic） |
| `pdf-vision` | PDF 视觉处理（`pdf2image`） |
| `paddle` | PaddleOCR（finreportparser VLM 可选） |
| `vlm` | 本地 VLM 后端（`transformers` + `torch`） |
| `formula` | 公式 OCR（`pix2text`） |

```bash
uv sync --extra dev --extra ricequant --extra instructor
```

## PDF 后端：finreportparser（vendored）

`src/finreportparser/` 是从 finpdfpro vendoring 而来的 PDF 布局解析包，
作为 reproagent 唯一主 PDF 后端（`PARSER_BACKEND=finpdfpro`，默认值）。
配置文件位于 `configs/{default,fast,max_quality}.yaml`，通过 `FINPDFPRO_MODE` 选择：

- `fast` — 快速模式
- `balanced` — 默认均衡模式
- `max-quality` — 最高质量模式

`FINPDFPRO_VLM_BACKEND=none`（默认）不依赖 paddle/torch；设为 `paddle_vl` / `smolvlm` / `llamacpp_http` 启用 VLM 增强（需对应 extras）。

```bash
uv run python -c "from finreportparser.config import load_config; print(load_config().mode)"
```

## 数据后端

数据后端通过 `DATA_SOURCE` 选择，与 aiminer 对齐：

| `DATA_SOURCE` | 说明 | 凭证 / 依赖 |
|---------------|------|-------------|
| `local` | 读取本地 parquet/csv（默认，离线可跑） | `LOCAL_DATA_PATH` 指向含 `prices.parquet` 的目录 |
| `ricequant` | 米筐商业数据（lazy import `rqdatac`） | `RQ_TOKEN` / `RQ_USER` + `RQ_PASS`，需 `--extra ricequant` |
| `qlib` | qlib 数据（lazy import） | `QLIB_CN_DATA_PATH`，需自行安装 `pyqlib` |
| `tushare` | tushare（暂未实现） | `TUSHARE_TOKEN` |

离线测试默认使用 `local` + `tests/fixtures/test_data/prices.parquet`。

## legacy_quant 旁路模块

`src/reproagent/legacy_quant/` 原样保留 `量化agent.zip` 的三文件（`factor_db` / `factor_research_pipeline` / `factor_library_dashboard`），
改为相对导入，作为可运行的原型旁路。**core 业务路径不依赖 legacy_quant**。

```bash
uv run python -m reproagent.legacy_quant   # seed demo + 生成 HTML 仪表盘到 /tmp
```

## CLI

```bash
reproagent --help
reproagent ingest path/to/report.pdf
reproagent reproduce path/to/report.pdf
reproagent library                 # 列出因子库
reproagent library --html          # 生成 HTML 仪表盘到 ~/.reproagent/wiki/
reproagent review                  # 处理人工复核队列
reproagent tui                     # 启动 Textual TUI
```

或：

```bash
python -m reproagent --help
```

### 离线 mock 示例（无需 LLM / 数据凭证）

```bash
# 摄入 fixture PDF（mock + local）
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run reproagent ingest tests/fixtures/sample_reports/minimal.pdf

# 离线全链路（mock LLM 提取 + local 数据回测）
OPENAI_API_KEY= ANTHROPIC_API_KEY= \
DATA_SOURCE=local \
LOCAL_DATA_PATH=tests/fixtures/test_data \
uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf
```

无 `LLM_API_KEY` 时，`LLMExtractor` 自动回退到确定性 mock 因子规格，便于离线开发与 CI。

## 包结构（摘要）

```
src/
  finreportparser/   # vendored PDF 布局解析后端（唯一主路径）
  reproagent/
    models/          # Pydantic 领域模型
    ingestion/       # 研报摄入 + 校验 + 复核队列
    parser/          # finpdfpro 布局 + LLM 结构化提取 + schema 校验
    reproducer/      # 因子计算（polars）+ 回测 + 指标 + evaluator_factory
    deviation/       # 偏差分析 + 根因 + 反思循环
    library/         # 因子库 + 分类 + index/wiki + HTML 仪表盘
    persistence/     # SQLModel + 路径约定
    cache/           # 文件系统缓存
    tui/             # Textual 前端
    legacy_quant/    # 量化agent.zip 旁路（原样保留）
    pipeline.py      # 端到端编排
    cli.py           # Typer CLI
configs/             # finreportparser YAML（default/fast/max_quality）
```

## 开发

```bash
make test
make lint
```

运行测试套件（离线，无需真实凭证）：

```bash
OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
```

数据与元数据默认写在 `~/.reproagent/`（见 `Settings` / `AppPaths`）。
