# 当前下一任务

## 上一任务（已完成）

~~Decision Trace 权威契约修复~~（`fix/decision-trace-authoritative-contract`，PR #35，Merge SHA `f5f4206`）。

- **状态**：已完成并合并。
- Signal Ledger / Decision Evidence 对齐生产权威持仓建议契约。
- 非法 `execution_size` 不再进入 Outcome/Signal/Evidence payload。
- 缺失 `trade_date` / `generated_at` 失败关闭，不补当前时间、不写库。
- 后端 not-live 全量 **1625 passed**；前端 214 passed；Vite build passed。
- **历史错误归档记录未回填**。

~~Scheduler import 测试顺序隔离修复~~（`fix/scheduler-test-isolation`，PR #33，Merge SHA `e857d43`）。

~~P2-4B Performance Attribution（收益归因）。~~

## 当前下一任务

**当前已授权产品任务：无。**

> 长期候选池见 [`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)（BK-01 ~ BK-10）。
> **候选事项不代表开发授权。**
> visual-overhaul 仍待用户决策。

## 待决定 / 本地目录

| 目录 | 状态 | 建议 |
|---|---|---|
| `Vibe-Research-product-backlog-docs` | PR #34 文档维护 worktree | 保留等待审查；不属于产品候选 |
| `Vibe-Research-visual-overhaul-20260729` | 活跃 worktree；本地实验；未提交 7 个前端文件 | 待用户决策是继续开发还是废弃 |
| `Vibe-Research-decision-trace-contract` | PR #35 已合并；worktree 与残留目录均已回收 | 已不存在本地残留 |
| `Vibe-Research-data-health-design` | worktree 已注销；本地仍含完整源码副本 | 未确认可安全删除，继续保留等待独立审计 |
| `Vibe-Research-decision-feedback-hardening` | 空目录残留；受 Windows 锁定 | 重启后重新确认为空再删除 |
| `Vibe-Research-trade-ledger-ui-git-backup-20260729-105111` | Git 备份；价值未最终确认 | **继续保留** |
