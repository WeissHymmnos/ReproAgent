# ReproAgent 相对公开量化平台的能力差距审查

> 审查对象：仓库现货（`uv run reproagent` + `src/reproagent/`）。
> 对标：WorldQuant BRAIN、Microsoft Qlib、QuantConnect LEAN、Two Sigma Venn / Factor Lens。
> 日期：2026-08-26。§6.1 任务内缺口补过一轮；本文件按补齐后的代码重评。
> 每条事实落到命令或源码路径。

---

## 0. 方法与边界

- **现货**：README 已声明、且代码能走到的入口与行为。
- **愿景**：只出现在 `masterplan.md` / `instruction.md` §14 / `agents/` 骨架里的，标 **aspirational**。
- 对标对象覆盖研报复现台、公式 alpha 沙盒、AI 投研工作流、事件驱动交易引擎、机构风险透镜。未公开的 Citadel / Renaissance / Two Sigma 生产栈标 **unknown**。Bloomberg 等终端只作非核心旁注。
- 组 (e)（组合 / 风险模型 / 实盘）是 README 明确非目标：矩阵保留以免忘掉，标 **任务外缺席**，不是「做失败」。
- 评分：**有** / **部分** / **无**（括号内一行证据）。

---

## 1. ReproAgent 现货清单

### 1.1 定位

`README.md`：卖方研报 PDF/Markdown → 解析因子 → 本地回测 → 与声称指标对偏差 → 最多三次根因修订 → 否则人工复核；通过的进本地因子库。A 股 + 转债。单机单用户，SQLite + Parquet。

能做：结构化提取、Polars 55+ 算子、IC/ICIR/夏普/回撤/换手、偏差自愈、反过拟合套件、数据守卫、未来函数 AST、因子库+wiki。

不做：实盘、组合优化、风险模型、编造研报没写的细节。

### 1.2 入口（`uv run reproagent --help`，版本 1.0.0）

| 命令 | 作用 | 路径 |
|---|---|---|
| `ingest` | upload → validate → SQLite | `cli.py` |
| `reproduce` / `text` | 端到端复现；`.md`/`.txt` 跳过 PDF | `pipeline.py` |
| `library` | 浏览；`--html` `--check-decay` | `library/manager.py` |
| `decay` | 库内 IC 衰减复查 | `library/decay_monitor.py` |
| `runs --list` | 列出 reproduce/reflection 运行记录 | `persistence/run_log.py` |
| `review` | 人工复核 | `ingestion/review_queue.py` |
| `benchmark` | GT 基准 | `benchmark/runner.py` |
| `serve` | 浏览器工作台 `:8765` | `web/app.py` |
| `tui` | 复现 / 库 / 复核三 Tab | `tui/app.py` |
| `mcp` | FastMCP 10 工具 | `mcp_server.py` |

`DATA_SOURCE`：`local` / `ricequant` / `qlib` / `tushare`（`settings.py`）。`PARSER_BACKEND` 仅 `finpdfpro`。`default_engine` 仅 `polars`。

### 1.3 管线

`pipeline.py`：ingest → parse（仅 finpdfpro）→ lookahead 硬拦截 → `DataLoader` + `apply_point_in_time` + `apply_guards` → Polars → `StrategyBacktester`（Delay/Decay/中性/截断/滑点/涨跌停不成交）→ 偏差/反思 → **入库门** `gate_register`（反过拟合 + 冗余）→ wiki，或复核。

每次尝试写 `data_dir/runs/*.json`。

### 1.4 引擎与仿真

- 65 算子，`polars_engine.py` `_CONTEXT`。`GroupNeutral` 仍是按日去均值；**行业中性走回测参数** `BacktestParams.neutralization`。
- `delay` 默认 1（次日收益）；`decay` 线性平滑；`truncation` 单票权重帽；`slippage_bps`；`limit_no_fill` 默认开。
- `engine=rqalpha`：`RiceQuantEval.compute` **fail-closed**，不再静默 Polars。

### 1.5 数据宇宙

- `all` / 全A **不再**映射沪深300（`pit.py` `FULL_MARKET_UNIVERSE_KEYS`；米筐走 `all_instruments(..., date=as_of)`）。
- 可选列：`list_date`/`delist_date`/`in_universe`/`ann_date` → 幸存者过滤 + 公告日滞后（`apply_point_in_time`）。**没有这些列就是 no-op**；默认 fixture 仍是静态 parquet 快照。
- 命名指数 csi300/500/1000：米筐 `index_components(index_id, date=as_of)`。
- 转债：`全转债`/`cb` → `cb_prices.parquet`。
- 守卫：ST / 停牌 / 新股 60 日 / 涨跌停 9.8%。

### 1.6 质量件

- 入库：`library/admission.py` 跑 DSR/PBO 等（`overfit_eval.py`）和 `check_redundancy`。冗余 → `status=review` 拒绝 ready。过拟合：记录并打 tag；`n_obs≥60` 才拒 ready。
- 衰减：`reproagent decay` 用 `ic.parquet` **尾部均值**当 current IC（`0.0` 是有效读数，不 `or orig`）。
- 仪表盘：Chart.js 卡片/KPI 含 Fitness、自相关、覆盖、生产相关（缺测 `n/a`）。生产相关现货恒为 n/a（没有生产簿）。

### 1.7 组 (e)

全库无组合优化器、风险模型、实盘路径。与 README 一致。

### 1.8 愿景（非现货）

| 处 | 内容 | 现货 |
|---|---|---|
| `agents/__init__.py` | 多 Agent | 骨架，`generate()` 返回 `[]` |
| `instruction.md` §14 | 蜂群流程 | 文档自承未编排 |
| `masterplan.md` rqalpha 引擎 | 独立回测 | fail-closed，未实现 |
| `ReplicationConfig.engine` 仍含 `rqalpha` | 可选引擎 | 选了就报错，不计算 |

---

## 2. 对标集合（公开出处）

未公开内部系统不评分。

### 2.1 WorldQuant BRAIN — 公式 alpha 沙盒

- <https://www.worldquant.com/brain/> — datasets、performance dashboards、value-add；400,000+ fields。
- <https://worldquantbrain.com/vi/alpha-examples> — Fast Expression；Delay-1；subindustry 中性；decay；单票上限；TOP3000。
- 仿真旋钮：<https://medium.com/@mapongo/worldquant-brain-how-to-apply-the-simulation-environment-settings-9dc232831bb6>
- 生态论文：Kakushadze, *101 Formulaic Alphas*, <https://arxiv.org/abs/1601.00991>

顾问提交研究，不经 BRAIN 下单。

### 2.2 Microsoft Qlib — AI 量化工作流

- <https://github.com/microsoft/qlib>
- `qrun`：<https://qlib.readthedocs.io/en/latest/component/workflow.html> — 数据→训练→信号分析→回测；**Recorder**。
- 数据层：<https://qlib.readthedocs.io/en/latest/component/data.html>
- 论文：<https://arxiv.org/abs/2009.11189>
- 文档链含 risk modeling、portfolio optimization、online serving。

### 2.3 QuantConnect LEAN — research = live

- <https://www.lean.io/> — 无幸存者偏差、公司行为、PIT 数据、滑点/冲击/券商/保证金；组合构建（等权 / MV / Black-Litterman）；风险插件；宣称 375k live algorithms。
- <https://www.quantconnect.com/docs/v2/lean-engine/getting-started>
- Time Frontier：<https://www.quantconnect.com/docs/v1/key-concepts/understanding-time>

### 2.4 Two Sigma Venn / Factor Lens — 机构风险透镜

- <https://www.twosigma.com/articles/introducing-the-two-sigma-factor-lens/> — holistic / parsimonious / orthogonal / actionable。
- Lasso 因子选择：<http://help.venn.twosigma.com/en/articles/1393204-two-sigma-factor-selection-methodology>

这是配置端风险归因，不是挖 alpha，也不是实盘。

### 2.5 非核心

Bloomberg / Wind / Choice 是终端，不进矩阵。

---

## 3. 维度矩阵

### 3.1 组 (a) PIT 数据 + 无幸存者偏差宇宙

| 机械 | ReproAgent | BRAIN | Qlib | LEAN | Venn |
|---|---|---|---|---|---|
| 点时序行情/基本面 | **部分** — Delay-1 默认；`ann_date` 滞后已接线，**依赖列是否存在**；默认 fixture 无公告日 | **有** — Delay 一等 | **部分** — 停牌 NaN、股票池日期区间 | **有** — PIT 数据集 + Time Frontier | **部分** — 宽基指数代理 |
| 无幸存者偏差宇宙 | **部分** — `list_date`/`delist_date` 过滤已接线；`all` 不再 CSI300 代理；米筐指数 `as_of` 成分；local 无列则仍是快照 | **有** — 平台维护 TOP3000 | **部分** — instruments 日期范围 | **有** — 上市/退市/并购 | **无** |
| 按日可交易宇宙 | **部分** — csi300/500/1000/转债/all；行业中性缺行业列时退回市场中性 | **有** — Region+Universe | **有** — instruments | **有** — Universe Selection | **无** |

### 3.2 组 (b) 表达式引擎 + 无前瞻 + 仿真真实感

| 机械 | ReproAgent | BRAIN | Qlib | LEAN | Venn |
|---|---|---|---|---|---|
| 表达式或模型引擎 | **有** — 65 算子 + LLM 抽公式；**无**可训练 ML | **有** — Fast Expression | **有** — 表达式 + GBDT/NN | **有** — Python/C# + 100+ 指标 | **无** |
| 无前瞻求值 | **有** — 负窗口拒绝；lookahead 硬进复核；Delay 可配 | **有** — Delay | **有** — `Ref` + 切段 | **有** — Time Frontier | **无** |
| Delay / Decay | **有** — `BacktestParams.delay`/`decay`；**无**独立仿真 UI（CLI/Web 未暴露旋钮） | **有** — 设置面板 | **部分** — 写在表达式里 | **有** — 调度+持仓 | **无** |
| 成本 / 冲击 | **部分** — 3 bps + `slippage_bps` + 涨跌停不成交；无冲击/券商/保证金 | **部分** — Fitness 罚换手 | **有** — open/close cost、涨跌停 | **有** — fill/slippage/fee/brokerage | **无** |
| 中性化 | **部分** — 参数 `market`/`industry`/`subindustry`；无行业列则退回市场去均值；算子 `GroupNeutral` 仍是日均值 | **有** — Market/Sector/Industry/subindustry | **部分** — 策略层 | **部分** — 风险插件 | **无** |

### 3.3 组 (c) 因子库 + 质量门 + 冗余/正交 + 衰减

| 机械 | ReproAgent | BRAIN | Qlib | LEAN | Venn |
|---|---|---|---|---|---|
| 因子/alpha 库 | **有** — SQLite + wiki + HTML + MCP | **有** — 提交与仪表盘 | **部分** — Alpha158/360，不是研报资产库 | **部分** — 社区算法 | **有** — 风险因子透镜（不同含义） |
| 质量门 | **部分** — 声称值偏差 + 健康 + lookahead + 入库 DSR/PBO/冗余；过拟合短样本只打标 | **有** — Sharpe/Turnover/Fitness/coverage/value-add | **部分** — 切段，无 DSR 门 | **部分** — 回测统计 | **有** — 透镜方法论 |
| 冗余 / 正交 | **部分** — 相关>0.7 拒 ready；**无**正交化变换 | **有** — 自相关/生产相关叙事 | **部分** — 可自算 | **无** | **有** — 透镜正交目标 |
| 衰减监控 | **有** — `decay` CLI + `ic.parquet` 尾部；无定时调度 | **部分** — 滚动仿真可见 | **部分** — Recorder 复跑 | **部分** — 实盘后验 | **部分** — 风险暴露随时间 |

### 3.4 组 (d) UX + 实验跟踪

| 机械 | ReproAgent | BRAIN | Qlib | LEAN | Venn |
|---|---|---|---|---|---|
| 交互研究 UX | **有** — CLI+TUI+本地 Web+MCP；单用户；Delay 等无工作台旋钮 | **有** — Web 仿真器 | **部分** — qrun + Notebook | **有** — 云+Jupyter+VSCode | **有** — 机构分析 UI |
| 实验跟踪 | **部分** — `runs/*.json` + 缓存键 + GT 基准；不是 Recorder/对比 UI | **部分** — 账号内仿真史 | **有** — Recorder | **有** — research=live 档案 | **部分** — 组合可复述 |

### 3.5 组 (e) 组合 / 风险 / 实盘

| 机械 | ReproAgent | BRAIN | Qlib | LEAN | Venn |
|---|---|---|---|---|---|
| 组合构建 | **无**（任务外） | **部分** — 向量+截断 | **有** — TopkDropout 等 | **有** — EW/MV/BL | **部分** — 配置建议 |
| 风险模型 | **无**（任务外） | **部分** — 中性+截断 | **有** — 文档链 | **有** — 风险插件 | **有** — Factor Lens |
| 实盘/模拟盘 | **无**（任务外） | **无** — 只提交研究 | **部分** — online serving | **有** — 同一引擎 live | **无** |

---

## 4. 品类错位

| 产品 | 卖什么 | 和 ReproAgent |
|---|---|---|
| ReproAgent | 中文卖方研报 **单因子忠实复现台** | 基准 |
| BRAIN | 全球公式 alpha 众包沙盒 | 仿真旋钮与质量雷达上限 |
| Qlib | 数据→模型→回测→线上 | ML 工作流与 Recorder；本仓只当数据源 |
| LEAN | 研究=回测=实盘 | 宇宙/成交/实盘上限 |
| Venn | 多资产风险透镜 | 正交产品 |

在 (e) 上「追上 LEAN/Venn」会变成另一个产品。

---

## 5. 现货上别人不做的

1. **PDF/Markdown 研报 → 结构化因子**（`finreportparser` + LLM schema）。对标四家都不是这条主路径。
2. **声称值偏差自愈**（反思 ≤3 次 + 复核队列）。
3. **单机 SQLite+Parquet**，离线可跑。
4. **反过拟合套件接到入库**（不再只是 MCP 旁路）。
5. **A 股微观结构 + 转债**。
6. **MCP 10 工具**把引擎暴露给 Agent 客户端。
7. **带 GT 的 `benchmark`**（minimal / cb-factor-investing）。
8. **衰减复查与实验 run 目录**已有 CLI。

---

## 6. 仍存在的差距

### 6.1 任务内（还值得做，但不再是「完全缺席」）

| 秩 | 缺口 | 现货证据 | 为何仍任务内 |
|---|---|---|---|
| 1 | **PIT 数据要靠列/供应商** | 无 `ann_date`/`delist_date` 则过滤器 no-op；默认 fixture 是快照；无公司行为（分红拆股）引擎 | 研报窗口的可投资集合仍可能偏 |
| 2 | **行业中性依赖行业列** | 没有 `industry`/`subindustry` 时退回市场去均值 | 金工研报普遍行业中性 |
| 3 | **仿真旋钮未进工作台 UI** | 参数在 `BacktestParams`，CLI/Web 没有 Delay/Decay/中性面板 | 研究员不能像 BRAIN 那样拧旋钮 |
| 4 | **成本仍是 bps 模型** | 无冲击、券商、保证金、逐笔成交 | 高换手量价因子夏普仍偏乐观 |
| 5 | **生产相关恒 n/a** | 没有生产簿/实盘相关可算 | Fitness 雷达缺 BRAIN 的 value-add 一维 |
| 6 | **实验对比偏薄** | JSON run 文件可列，不能像 Recorder 对比两次实验 | 反思循环仍难做「公式×窗口」面板 |
| 7 | **无 ML 工作流** | 只有公式引擎；`DATA_SOURCE=qlib` 只拉行情 | 研报里的模型类因子无法训练 |
| 8 | **过拟合门偏松** | `n_obs<60` 只打标不拒 ready | 短窗复现容易把过拟合因子放进库 |

### 6.2 任务外（章程排除）

实盘/OMS、组合优化、风险模型/Factor Lens、全球多资产、多用户云、克隆 BRAIN/Qlib/LEAN。组 (e) 的「无」= deferred。

---

## 7. 结论

ReproAgent 是 **中文卖方研报 → 可复现单因子资产** 的本机工作台，不是通用量化 OS。

相对初稿：任务内「完全缺席」的 Delay/Decay/行业中性参数、入库质量门、衰减 CLI、run 记录、PIT 过滤器、后端撒谎，已经接到现货。剩下的短板是 **数据完整性（列/公司行为）**、**仿真 UI 与微观结构深度**、以及 **ML/实验平台**——不是章程里的实盘和组合栈。

- vs **BRAIN**：有同类旋钮的数据模型，缺云端仿真器、400k 字段、生产相关。多了研报抽取与偏差自愈。
- vs **Qlib**：不做模型训练与 Recorder；Qlib 不做 PDF 研报。
- vs **LEAN**：不做 research=live、公司行为、可插拔成交。LEAN 不做研报声称值收敛。
- vs **Venn**：层不同——Venn 解释组合风险，ReproAgent 生产单因子。

---

## 8. 来源

**本仓：** `cli.py`、`settings.py`、`pipeline.py`、`polars_engine.py`、`backtester.py`、`pit.py`、`sim_transforms.py`、`admission.py`、`decay_monitor.py`、`dashboard.py`、`run_log.py`、`rqalpha_engine.py`；非目标 `README.md`「不要指望它做的事」。

**对标：** BRAIN 官网与 alpha 例、Qlib GitHub/qrun 文档与 arXiv:2009.11189、LEAN lean.io 与 Time Frontier、Two Sigma Factor Lens 介绍文。
