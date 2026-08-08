# 复现基准语料库 (Reproduction Benchmark Corpus)

验证 `reproagent` 因子公式可执行性，以及（可选）与研报声称指标的偏差。

## 目录结构

```
benchmark/
├── README.md
├── catalog.yaml           ← 语料索引（status / extraction_fidelity）
└── {report_id}/
    └── ground_truth.yaml  ← 人工标注的因子 ground truth
```

相关本地数据：

- `tests/fixtures/test_data/prices.parquet` — 股票小样本
- `tests/fixtures/test_data/cb_prices.parquet` — 转债合成 panel（含 ytm / premium_rate 等）

## ground_truth.yaml schema

```yaml
report_id: "unique-id"
broker: "华泰证券"
report_date: "2026-05-18"
report_title: "研报标题"
backtest_params:
  start_date: "2023-01-03"
  end_date: "2023-02-27"
factors:
  - name: "ytm_bondness"
    name_cn: "债性(YTM)"
    formula: "ytm"
    input_fields: ["ytm"]
    rebalance_frequency: "monthly"
    universe: "全转债"
    lookback_window: null
    reported_metrics:
      ic_mean: null          # null = 仅校验可计算
      ic_ir: null
      long_short_return: null
      sharpe_ratio: null
      max_drawdown: null
    annotation_notes: "..."
```

### 比对规则

| reported_metrics | 通过条件 |
|------------------|----------|
| 全部为 null | 因子值非全 NaN（`values_ok`） |
| 含具体数值 | `DeviationAnalyzer` 容忍区间门控 |

### catalog 字段

| 字段 | 含义 |
|------|------|
| `status` | `pending` / `annotated` / `validated` |
| `extraction_fidelity` | `true` 时 CI 还校验 mock/LLM 提取因子名与公式 |

## 命令

```bash
# 列表
uv run reproagent benchmark --list

# ground_truth 全链路（不依赖 LLM）
DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
  uv run reproagent benchmark --run minimal

DATA_SOURCE=local LOCAL_DATA_PATH=tests/fixtures/test_data \
  uv run reproagent benchmark --run cb-factor-investing

uv run reproagent benchmark --run-all
uv run reproagent benchmark --report
```

结果写入 `~/.reproagent/benchmark/{report_id}/result.json`。

## 当前语料

| report_id | 状态 | 因子数 | 说明 |
|-----------|------|--------|------|
| `minimal` | annotated | 1 | mock 小 PDF + 提取 fidelity |
| `cb-factor-investing` | annotated | 6 | 华泰转债手册代表因子；引擎比对 |

## 标注 SOP（新增研报）

1. 在 `catalog.yaml` 增加条目（先 `pending`）
2. 创建 `{report_id}/ground_truth.yaml`，至少填 `name` / `formula` / `input_fields` / `universe`
3. 若需转债字段，确保 `cb_prices.parquet` 或数据源含对应列
4. 本地跑 `benchmark --run {id}`，确认 `status=passed`
5. 将 `status` 改为 `annotated`；有真实声称指标并核对后改为 `validated`
6. 仅当 mock/LLM 也能稳定提取同名因子时，设 `extraction_fidelity: true`
