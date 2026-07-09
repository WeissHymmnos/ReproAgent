# ReproAgent

研报因子自动复现系统：上传 PDF 卖方研报 → 解析因子定义 → 回测复现 → 偏差自愈 → 入因子库。

施工蓝图见 [masterplan.md](./masterplan.md)。当前仓库为可安装脚手架 + 模块抽象（Protocol / 类签名 / 领域模型），业务逻辑待按文件填空实现。

## 要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）

## 安装

```bash
uv sync --extra dev
cp .env.example .env   # 填入 LLM_API_KEY 等
```

可选 extras：`parser-marker`、`parser-llama`、`parser-mineru`、`rqalpha`、`pdf-vision`、`instructor`。

## CLI

```bash
reproagent --help
reproagent ingest path/to/report.pdf
reproagent reproduce path/to/report.pdf
reproagent library
reproagent review
reproagent tui
```

或：

```bash
python -m reproagent --help
```

## 包结构（摘要）

```
src/reproagent/
  models/        # Pydantic 领域模型
  ingestion/     # 研报摄入
  parser/        # 布局 + LLM 提取
  reproducer/    # 因子计算与回测
  deviation/     # 偏差分析与反思循环
  library/       # 因子库
  persistence/   # SQLModel + 路径约定
  cache/         # 文件系统缓存
  tui/           # Textual 前端
  pipeline.py    # 端到端编排桩
```

## 开发

```bash
make test
make lint
```

数据与元数据默认写在 `~/.reproagent/`（见 `Settings` / `AppPaths`）。
