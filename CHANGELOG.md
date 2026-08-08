# Changelog

## 1.0.0 — 2026-08-08

### 完成体（v1.0）

- **Benchmark 全链路**：`reproagent benchmark --run <id>` 基于 ground_truth 计算因子并做偏差比对
- **黄金样本**：`minimal` + 华泰转债手册 `cb-factor-investing`（6 因子）`validated`
- **转债数据层**：字段字典 / `全转债` universe / `cb_prices.parquet` fixture
- **Markdown 捷径**：`reproagent text -f report.md`（`reproduce_text`）
- **长文分块提取**：按页/长度切分 LLM 提取，合并去重
- **置信度门控**：低置信 / 高 WARN 映射默认进人工复核
- **反思增强**：按 root_cause 启发式修订 + ExperienceMemory 注入 prompt
- **根因 LLM fallback**：有 API key 时 instructor 结构化分类；无 key 安全降级
- **MCP**：`score_factor` / `run_anti_overfitting` / `run_backtest` 接真实回测与反过拟合
- **统一输出 schema**：pipeline 返回 `status/source/summary/factors`
- **测试**：167+ 离线测试全绿

### 兼容性

- CLI 命令向后兼容；因子库 entry version 默认 `1.0.0`
- `APP_ENV=prod` 仍要求 `LLM_API_KEY`，禁止静默 mock

## 0.1.0 — 2026-07

- 六子系统脚手架 + finreportparser vendor
- mock e2e、TUI、反过拟合库、数据守卫
