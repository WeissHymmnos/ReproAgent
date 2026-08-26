# ReproAgent

> English overview: [README_EN.md](README_EN.md)

把卖方研报里的因子自动复现出来。喂一篇 PDF 研报(或者现成的 Markdown),
它解析出因子定义,在本地数据上跑回测,跟研报声称的指标对偏差;
对不上就按根因改公式重试,最多三次,还不行就进人工复核。
跑通的因子沉淀到本地因子库。

面向 A 股和转债市场。单机单用户,SQLite 加 Parquet 存储,不需要部署任何服务。

## 上手

需要 Python 3.12+,包管理用 uv。

    git clone <repo-url> && cd reproagent
    uv sync --extra dev

离线体验,不需要任何 API key:

    OPENAI_API_KEY= ANTHROPIC_API_KEY= DATA_SOURCE=local \
      LOCAL_DATA_PATH=tests/fixtures/test_data \
      uv run reproagent reproduce tests/fixtures/sample_reports/minimal.pdf

仓库自带两个带人工标注答案的基准,同样不依赖 LLM:

    DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
      uv run reproagent benchmark --run minimal
    DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
      uv run reproagent benchmark --run cb-factor-investing

手里已经是 Markdown 版研报的话,跳过 PDF 解析直接来:

    uv run reproagent text -f report.md -b 华泰证券

生产环境:`cp .env.example .env` 填好 `LLM_API_KEY`,然后

    APP_ENV=prod DATA_SOURCE=tushare uv run reproagent reproduce report.pdf

prod 模式禁掉 mock 提取和公式回退,没有 key 会直接拒绝运行,不会悄悄降级。

## 能做什么,不能做什么

能做的部分:

- PDF/Markdown 到结构化因子定义,LLM 结构化提取,长文自动分块合并
- Polars 表达式引擎,55+ 算子,分组回测给出 IC/ICIR/夏普/最大回撤/换手
- 复现指标与研报声称值做偏差分析,按根因分类定向修订,重试不超过三次
- 反过拟合体检:DSR/PBO/MinBTL/bootstrap CI/walk-forward/placebo 一整套
- 数据守卫:ST、停牌、新股、涨跌停处理;未来函数 AST 检测
- 通过门控的进因子库(附 wiki 页面),拿不准的进人工复核队列
- 工作台行情带和数据源健康检查

不要指望它做的事:

- 实盘交易
- 组合优化和风险模型——它只管单因子复现这一段
- 编造研报里没写的细节,提取不到的东西会走复核流程

## 接口

以 CLI 为主:

    reproagent ingest report.pdf      # 校验并入库
    reproagent reproduce report.pdf   # 端到端复现
    reproagent text -f report.md      # Markdown 直接进
    reproagent library [--html]       # 浏览因子库
    reproagent review --list | --approve ID | --reject ID
    reproagent benchmark --list | --run ID | --run-all | --report
    reproagent serve                  # 浏览器工作台,默认 http://127.0.0.1:8765
    reproagent tui                    # 终端界面
    reproagent mcp                    # MCP 服务,给支持 MCP 的客户端调用
    reproagent decay                  # 因子库 IC 衰减复查
    reproagent runs --list            # 列出 reproduce/reflection 运行记录
    reproagent market                 # 数据源健康 + 最近交易日行情带

`reproduce` 和 `text` 输出统一结构的 JSON(`status/source/summary/factors/data_context`),
方便脚本消费。注意 `soft_passed` 这个状态:指标没完全对上、但复现结果健康,因子已经入库,
和干净的 `passed` 是两回事,批处理时建议分开统计。

## 配置

配置全走环境变量,`.env` 也认。常用的几个:

| 变量 | 说明 | 默认 |
|------|------|------|
| `APP_ENV` | dev 允许 mock 和回退;prod 全部严格阻断 | `dev` |
| `LLM_API_KEY` | 提取用的 LLM key | 空 |
| `LLM_PROVIDER` / `LLM_MODEL` | `openai` 或 `anthropic` | `anthropic` / `claude-sonnet-4-5` |
| `PARSER_BACKEND` | PDF 解析后端，仅 `finpdfpro` | `finpdfpro` |
| `DATA_SOURCE` | `local` / `ricequant` / `qlib` / `tushare` | `local` |
| `LOCAL_DATA_PATH` | local 模式的 parquet 目录 | `tests/fixtures/test_data` |

各数据源要准备什么:

- **local**:一个 `prices.parquet`(可选加 `fundamentals.parquet`、`cb_prices.parquet`),CI 和离线开发够用
- **tushare / ricequant**:各自的 token,加上对应 extra
- **qlib**:本地 qlib 数据目录（`uv sync --extra qlib` 安装 `pyqlib`）

转债 universe 写 `全转债`、`cb` 或 `convertible` 时会优先读 `cb_prices.parquet`。

可选 extra:`instructor`(结构化提取)、`ricequant`、`tushare`、`qlib`、`paddle`(OCR)、`vlm`(本地视觉模型)、`formula`(公式识别)、`mcp`。

## 测试

    make test    # 或者 OPENAI_API_KEY= ANTHROPIC_API_KEY= uv run pytest -q
    make lint

改了引擎和管线相关的代码,建议顺手跑一遍 `benchmark --run-all`,
ground truth 会拦住大部分行为回归。

## 代码结构

`src/reproagent/` 按流水线五段分包:models、parser、reproducer、deviation、library,
外围是 ingestion、benchmark、web、tui、persistence、cache、memory、agents;
PDF 解析后端 vendor 在 `src/finreportparser/`。
想读懂内部逻辑,从 `pipeline.py` 的 `reproduce_report` / `reproduce_text` 顺着往下看最顺。

## License

MIT
