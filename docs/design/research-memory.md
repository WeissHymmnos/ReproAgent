# Research Memory 设计（XAlpha 启发 · Phase 0）

## 1. 目的

将 XAlpha 的**多源研究记忆**思想落到 ReproAgent，服务「研报复现」而非「挖新因子」：

- **Report knowledge memory**：研报吸收为结构化线索（可行性 / 机制族 / archetype），不把 raw PDF 塞进 prompt。
- **Discovery feedback memory**：复现成功/失败写成 GOOD/BAD，供后续反思与路由复用。

本文件对应实施计划 Phase 0：**只定 schema 与挂载约定，不改 pipeline 业务行为**。

## 2. 与 XAlpha 的映射

| XAlpha | ReproAgent |
|--------|------------|
| RMA A-layer KEEP/DROP | `ReportKnowledgeAtom.a_decision` + 数据契约理由 |
| RMA B-layer family | `MechanismFamily` |
| RMA C-layer archetype | `ResearchArchetype`（线索，非公式） |
| GOOD / BAD feedback | `FeedbackRecord.kind` |
| Cross Brain 回写 | 后续 `memory.writer` 钩子（Phase 2+） |
| Macro 路由 | 后续 `plan` CLI（Phase 4，可选） |

## 3. 存储布局

```text
~/.reproagent/
  reproagent.db                 # SQLite：knowledge / archetypes / feedback / review
  memory/
    report_knowledge/           # 可选导出
    feedback/good|bad/*.jsonl   # 可选旁路导出
    cycles/                     # Phase 4
```

`AppPaths.memory_dir` 等属性在 `paths.py` 中定义；`ensure_layout()` 创建目录。

## 4. 领域模型（`reproagent.models.memory`）

- `MechanismFamily` — 机制族枚举（momentum / reversal / value / …）
- `EligibilityDecision` — KEEP | DROP
- `ReportKnowledgeAtom` — 单条研报证据吸收结果
- `ResearchArchetype` — C 层可行动线索
- `FeedbackKind` — GOOD | BAD
- `FeedbackRecord` — 机制级反馈（含 failure_type / avoid_rule / repair_hint）
- `MemoryWriteEvent` — 审计（可选）
- `FeedbackQuery` — 检索条件（Phase 2 使用）

## 5. 表（`persistence.tables`）

| 表 | 用途 |
|----|------|
| `report_knowledge` | knowledge atoms |
| `archetypes` | C 层 archetype |
| `feedback_memory` | GOOD/BAD |
| `manual_review_queue.payload_json` | 结构化复核载荷（兼容旧行默认 `{}`） |

`init_db` → `create_all` 对新表自动建表。已有 DB 缺列时由 `init_db` 内轻量 `ALTER` 补 `payload_json`（见 `db.py`）。

## 6. 读写 API（Phase 0 桩）

`reproagent.memory.store.MemoryStore`：

- `save_knowledge` / `list_knowledge`
- `save_archetype` / `get_archetype`
- `save_feedback` / `query_feedback`
- 底层经 `Repository` 持久化

**Phase 0 不调用** pipeline / reflection；Phase 2 再挂钩。

## 7. 已实现阶段（摘要）

| Phase | 状态 | 要点 |
|-------|------|------|
| 0 Schema | ✅ | models / tables / MemoryStore |
| 1 RMA-lite | ✅ | `memory/rma.py` A 门 + absorb；不可行短路 |
| 2 Feedback | ✅ | GOOD/BAD 写入；反思 prompt 注入；`SKIP_MOCK_REFLECTION` |
| 3 Cross-lite | ✅ | FAA 归因、`tier` elite/normal、入队 dedupe |
| 4 Macro-lite | ✅ | `reproagent memory show\|plan\|export` |

配置：`MEMORY_ENABLED`、`SKIP_MOCK_REFLECTION`、`MAX_REFLECTION_ITERATIONS`。

## 8. 非目标

- 不实现 XAlpha Micro 进化（mutation/crossover）
- 不强制向量库
- mock 反馈必须带 `source=mock`，prod 路由默认忽略
