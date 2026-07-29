# 当前下一任务

## 上一任务（已完成）

~~Scheduler import 测试顺序隔离修复~~（`fix/scheduler-test-isolation`，PR #33，Merge SHA `e857d43`）。

- **状态**：已完成。独立 `sys.executable` 子进程探针验证 `import app`，消除测试间顺序依赖。
- 后端 not-live 全量测试连续两次 1606 passed, 0 failed。

~~P2-4B Performance Attribution（收益归因）。~~

- **状态**：已完成开发与测试全覆盖
- 独立 SQLite 库 `performance_attribution.sqlite3`，加权平均成本法
- REST API: `GET /api/performance-attribution`, `POST /api/performance-attribution/snapshot`, `GET /api/performance-attribution/snapshots`, `GET /api/performance-attribution/snapshots/{id}`
- 前端 `/performance-attribution` 收益归因看板

## 当前下一任务

**无已授权产品任务。** 等待产品优先级指令。

> 长期产品候选池见 [`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)（BK-01 ~ BK-10）。候选功能未获授权，禁止开发。

## 待决定

| 目录 | 说明 | 建议 |
|---|---|---|
| `Vibe-Research-visual-overhaul-20260729` | 含未提交前端改动（`frontend/index.html`, `Layout.tsx`, `GlassCard.tsx`） | 继续开发形成 PR，或确认废弃后安全备份/删除 |
| `Vibe-Research-data-health-design` | PR #23 的 Data Health design worktree，主仓库功能已完成 | 审计其中是否有稳定分支没有的有效设计文档；没有则回收 |
