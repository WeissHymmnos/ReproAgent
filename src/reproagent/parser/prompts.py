"""Jinja2 提取 / 反思提示模板。"""

from __future__ import annotations

from jinja2 import Template

EXTRACTION_PROMPT = Template(
    """你是一位量化研究分析师。从中国 A 股卖方研报中提取因子定义。

对每个因子，提取：
- factor_name: 英文名/规范化名
- factor_name_cn: 研报中文原名
- formula: 数学公式（LaTeX 或结构化伪代码）
- input_fields: 输入字段列表
- computation_steps: 有序计算步骤
- universe / rebalance_frequency / reported_metrics
- extraction_confidence / source_pages

研报 Markdown:
{{ markdown }}

缺失值用 null，不要编造。
"""
)

REFLECTION_PROMPT = Template(
    """你正在复现中国卖方研报中的量化因子。

## 原始因子定义
- 名称: {{ original_spec.factor_name }} ({{ original_spec.factor_name_cn }})
- 公式: {{ original_spec.formula }}
- 股票池: {{ original_spec.universe }}
- 调仓: {{ original_spec.rebalance_frequency }}

## 之前的复现尝试
{% for step in history %}
### 尝试 {{ loop.index }}
- 使用公式: {{ step.revised_config.factor_specs[0].formula }}
{% set dev = step.deviation_report %}
- 偏差:
  - IC 均值偏差: {{ dev.metric_deviations.get("ic_mean", "N/A") if dev else "N/A" }}
  - 多空年化收益偏差: {{ dev.metric_deviations.get("long_short_return", "N/A") if dev else "N/A" }}
  - 夏普偏差: {{ dev.metric_deviations.get("sharpe", "N/A") if dev else "N/A" }}
- 根因分类: {{ dev.root_cause.value if dev else "N/A" }}
- 详情: {{ dev.root_cause_detail if dev else "" }}
{% endfor %}

## 最近一次偏差
- IC 均值偏差: {{ latest_deviation.metric_deviations.get("ic_mean") }}
- 根因: {{ latest_deviation.root_cause.value }}
- 详情: {{ latest_deviation.root_cause_detail }}

请修订因子定义以减少偏差，聚焦于识别出的根因。输出修订后的完整 ParsedFactorSpec。
"""
)
