# 当前下一任务

## 上一任务（已完成）

~~P2-2 Signal Ledger（信号账本）。~~

- **状态**：已完成开发与测试全覆盖
- 数据库 `decision_trace.sqlite3` (新增 `signal_entries` 与 `decision_outcomes` 数据表)
- REST API: `GET /api/signal-ledger`, `GET /api/signal-ledger/run/{decision_run_id}`
- 前端 `/signal-ledger` 页面与 7 阶段流水时间线，最终裁决结果卡片与参数回显

## 当前下一任务

**P2-3 Account Capital Constraints (账户资金与可用现金参与决策裁决)**

- **描述**：引入 `account_execution_policy.json`，在建议计算中应用资金分配与仓位整手限制（按 100 股向下取整、按代码字典序仲裁）。
- **要求**：不修改外部接口，不向网络泄露账户资产。
- **自动推进**：P2-2 合并后自动进入 P2-3，无需重新发起确认。
