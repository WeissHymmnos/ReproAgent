# 复现基准语料库 (Reproduction Benchmark Corpus)

验证 `reproagent` 从研报中提取因子定义并复现回测指标的准确率。

## 目录结构

```
benchmark/
├── README.md              ← 本文件
├── catalog.yaml           ← 语料索引
└── {report_id}/           ← 每篇研报一个子目录
    ├── report.pdf         ← 原始 PDF（或符号链接到仓库根目录）
    ├── ground_truth.yaml  ← 人工标注的因子 ground truth
    └── expected_metrics.yaml  ← 预期回测指标与容忍区间
```

## ground_truth.yaml schema

```yaml
report_id: "unique-id"
broker: "中信证券"
report_date: "2024-03-15"
report_title: "研报标题"
factors:
  - name: "factor_english_name"
    name_cn: "因子中文名"
    formula: "close / Ref(close, 20) - 1"
    formula_latex: "r_{t-20,t}"
    input_fields: ["close"]
    rebalance_frequency: "monthly"
    universe: "全A股剔除ST和上市不足60日"
    lookback_window: 20
    parameters:
      momentum_period: 20
      holding_period: 20
    reported_metrics:
      ic_mean: 0.045
      ic_ir: 0.52
      long_short_return: 0.12
      sharpe_ratio: 1.15
      max_drawdown: 0.08
    annotation_notes: "原文第7页表3，使用后复权价格"
```

## 语料管理

```bash
# 列出所有基准报告
reproagent benchmark --list

# 对单篇研报运行全流程 + 对比 ground truth
reproagent benchmark --run REPORT_ID

# 批量运行
reproagent benchmark --run-all

# 生成汇总报告
reproagent benchmark --report
```

## 语料来源

1. **阶段一**（进行中）：QuantsPlaybook 已验证研报
2. **阶段二**（计划中）：zer0factor workspace 标注
3. **阶段三**（计划中）：2024-2026 新发研报
