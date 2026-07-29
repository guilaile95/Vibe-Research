# 当前下一任务

## 上一任务（已完成）

~~P2-1 Explainability / Evidence Layer（决策依据层）。~~

- **状态**：已完成开发与测试全覆盖
- 数据库 `decision_trace.sqlite3` (`decision_runs`, `evidence_items`, `explanation_items`)
- REST API: `GET /api/decision-evidence`, `GET /api/decision-evidence/{id}`, `GET /api/decision-evidence/by-advice`
- 前端 `/decision-evidence` 探索看板与运行详情 Modal，持仓页打通「查看决策依据」跳转

## 当前下一任务

**P2-2 Signal Ledger (信号账本)**

- **描述**：记录系统内部实际发生的信号、规则和裁决过程，解答信号对决策的支持、限制或阻止效应。
- **关联数据库**：`decision_trace.sqlite3` (新增 `signal_entries` 与 `decision_outcomes` 数据表)
- **要求**：不虚构无来源的综合得分或权重；不改变 Validator 规则与 Prompt 审计语义。
- **自动推进**：P2-1 PR 合并后从最新稳定 SHA 创建分支 `feat/signal-ledger` 并全自动推进，无需重复等待确认。
