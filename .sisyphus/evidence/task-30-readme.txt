5:PDF 布局解析由 vendored 的 [`finreportparser`](./src/finreportparser)（源自 finpdfpro）提供，作为唯一主 PDF 后端；
6:非 PDF 逻辑按 [masterplan.md](./masterplan.md) 实现，数据后端对齐 aiminer（`local` / `ricequant` / `qlib`），
7:并保留 `量化agent.zip` 原样旁路于 `legacy_quant`。
25:| `ricequant` | 安装 `rqdatac`，启用 ricequant 数据后端 |
26:| `qlib` | qlib 数据后端（需自行安装 `pyqlib`） |
30:| `paddle` | PaddleOCR（finreportparser VLM 可选） |
35:uv sync --extra dev --extra ricequant --extra instructor
38:## PDF 后端：finreportparser（vendored）
40:`src/finreportparser/` 是从 finpdfpro vendoring 而来的 PDF 布局解析包，
41:作为 reproagent 唯一主 PDF 后端（`PARSER_BACKEND=finpdfpro`，默认值）。
51:uv run python -c "from finreportparser.config import load_config; print(load_config().mode)"
61:| `ricequant` | 米筐商业数据（lazy import `rqdatac`） | `RQ_TOKEN` / `RQ_USER` + `RQ_PASS`，需 `--extra ricequant` |
62:| `qlib` | qlib 数据（lazy import） | `QLIB_CN_DATA_PATH`，需自行安装 `pyqlib` |
67:## legacy_quant 旁路模块
69:`src/reproagent/legacy_quant/` 原样保留 `量化agent.zip` 的三文件（`factor_db` / `factor_research_pipeline` / `factor_library_dashboard`），
70:改为相对导入，作为可运行的原型旁路。**core 业务路径不依赖 legacy_quant**。
73:uv run python -m reproagent.legacy_quant   # seed demo + 生成 HTML 仪表盘到 /tmp
113:  finreportparser/   # vendored PDF 布局解析后端（唯一主路径）
117:    parser/          # finpdfpro 布局 + LLM 结构化提取 + schema 校验
124:    legacy_quant/    # 量化agent.zip 旁路（原样保留）
127:configs/             # finreportparser YAML（default/fast/max_quality）
