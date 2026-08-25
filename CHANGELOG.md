# Changelog

## 1.0.0 — 2026-08-08

- benchmark 子命令:按 ground_truth 跑因子并做偏差比对(`benchmark --run <id>`)
- 内置两组黄金样本:minimal,以及华泰转债手册 cb-factor-investing(6 因子),均已标注 validated
- 转债数据层:字段字典、`全转债` universe、cb_prices.parquet fixture
- `reproagent text -f report.md`:Markdown 直进,跳过 PDF 解析
- 长研报自动分块提取,合并去重
- 置信度门控:低置信或高 WARN 映射默认进人工复核
- 反思循环按根因启发式修订,ExperienceMemory 注入 prompt
- 根因分类支持 LLM fallback:有 key 走 instructor 结构化,无 key 安全降级
- MCP 工具接真实回测与反过拟合(score_factor / run_anti_overfitting / run_backtest)
- pipeline 输出统一为 status/source/summary/factors 结构
- 离线测试 167+ 全绿

兼容性:CLI 命令向后兼容;因子库 entry version 默认 1.0.0;APP_ENV=prod 仍要求 LLM_API_KEY 且禁止静默 mock。

## 0.1.0 — 2026-07

- 六子系统脚手架,vendor 进 finreportparser
- mock e2e、TUI、反过拟合库、数据守卫
