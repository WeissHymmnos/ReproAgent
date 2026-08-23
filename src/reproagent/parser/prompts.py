"""Jinja2 提取 / 反思提示模板。"""

from __future__ import annotations

from jinja2 import Template

EXTRACTION_PROMPT = Template(
    """你是一位量化研究分析师。从中国 A 股卖方研报中提取因子定义。

对每个因子，提取：
- factor_name: 英文名/规范化名
- factor_name_cn: 研报中文原名
- formula: **单行可执行表达式**（Python 风格），只能使用：
  算子: Rank, CSZScore, Ref, Mean, Std, Sum, Delta, EMA, Abs, Log, Sign, Sqrt, Pow, Max, Min
  字段: open, high, low, close, volume, amount, market_cap, pe_ratio, pb_ratio, return_on_equity
  示例: close/Ref(close,20)-1
  示例: -1*CSZScore(Log(market_cap))
  示例: CSZScore(return_on_equity)
  示例: -1*CSZScore(pe_ratio)
  禁止: LaTeX、中文、赋值句、叙述文字、未定义变量、Resid 多参回归
- input_fields: 规范英文字段名
- computation_steps: 步骤
- universe: 仅 csi300 / csi500 / csi1000 / 全A股 / 全转债
- rebalance_frequency
- reported_metrics: 仅正文有明确数字时填写，否则全 null
- extraction_confidence / source_pages

研报 Markdown:
{{ markdown }}

缺失用 null。**输出研报中所有可识别因子**（可多个，勿合并成一个）。
每个 formula 必须是可执行单行表达式（仅白名单算子/字段）。
时序算子 Std/Mean/Sum/EMA/Delta 必须带整数窗口（如 Std(x,20)、Mean(volume,20)）。
若某因子依赖另类数据/图网络/分析师一致预期等**白名单外字段**，**不要编造** ROE/动量/市值顶替，
也不要写未定义变量——直接省略该因子。
universe 只能是 csi300 / csi500 / csi1000 / 全A股 / 全转债（与正文一致）。
禁止罐头式一律输出 close/Ref(close,20)-1 或 CSZScore(return_on_equity)，除非正文明确是该因子。
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
{% set ls_dev = dev.metric_deviations.get("long_short_annual_return", "N/A") if dev else "N/A" %}
  - 多空年化收益偏差: {{ ls_dev }}
  - 夏普偏差: {{ dev.metric_deviations.get("sharpe_ratio", "N/A") if dev else "N/A" }}
- 根因分类: {{ dev.root_cause.value if dev else "N/A" }}
- 详情: {{ dev.root_cause_detail if dev else "" }}
{% endfor %}

## 最近一次偏差
- IC 均值偏差: {{ latest_deviation.metric_deviations.get("ic_mean") }}
- 根因: {{ latest_deviation.root_cause.value }}
- 详情: {{ latest_deviation.root_cause_detail }}

## 根因对应修订建议
{% if latest_deviation.root_cause.value == "LOOKAHEAD_BIAS" %}
- 对价格字段加 Ref(x, 1) 滞后；检查 shift 方向
{% elif latest_deviation.root_cause.value == "FORMULA_ERROR" %}
- 检查算子与符号方向；尝试 CSZScore/Rank 标准化
{% elif latest_deviation.root_cause.value == "PARAMETER_ERROR" %}
- 调整 lookback / 调仓频率 / 分组数
{% elif latest_deviation.root_cause.value == "UNIVERSE_MISMATCH" %}
- 切换股票池（csi300/csi500/全A/全转债）
{% elif latest_deviation.root_cause.value == "DATA_MISMATCH" %}
- 检查字段映射与复权；使用 Rank 削弱量纲
{% else %}
- 综合检查公式、参数与数据口径
{% endif %}

{% if experience_context %}
## 跨报告经验记忆
{{ experience_context }}
{% endif %}

请修订因子定义以减少偏差，聚焦于识别出的根因。
公式必须使用白名单算子（Rank/Ref/Mean/Std/CSZScore 等）。
输出修订后的完整 ParsedFactorSpec。
"""
)

ROOT_CAUSE_PROMPT = Template(
    """你是量化复现诊断助手。根据复现偏差模式判断根因类别。

可选类别（只能选一个）：
- DATA_MISMATCH: 数据字段/复权/口径整体偏移
- FORMULA_ERROR: 公式符号或算子错误
- PARAMETER_ERROR: 窗口/调仓等参数错误
- UNIVERSE_MISMATCH: 股票池不一致
- LOOKAHEAD_BIAS: 未来函数或时点错误
- UNKNOWN: 无法判断

因子公式: {{ formula }}
股票池: {{ universe }}
指标偏差 (reproduced - reported): {{ deviations }}
详情: {{ detail }}

只输出类别枚举值对应的结构化结果。
"""
)
