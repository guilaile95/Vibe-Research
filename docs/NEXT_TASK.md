# 当前下一任务

## 上一任务（已完成）

~~P2-4B Performance Attribution（收益归因）。~~

- **状态**：已完成开发与测试全覆盖
- 独立 SQLite 库 `performance_attribution.sqlite3`，加权平均成本法
- REST API: `GET /api/performance-attribution`, `POST /api/performance-attribution/snapshot`, `GET /api/performance-attribution/snapshots`, `GET /api/performance-attribution/snapshots/{id}`
- 前端 `/performance-attribution` 收益归因看板

## 当前下一任务

**Scheduler import 测试顺序隔离修复**（`fix/scheduler-test-isolation`）。

- **描述**：`test_import_app_does_not_start_scheduler` 原方案检查当前 pytest 进程的全局线程状态，导致测试间顺序依赖；改为独立 `sys.executable` 子进程验证 `import app`。
- **要求**：不修改 Scheduler 产品逻辑；两次全量 not-live 回归 0 failed。
- **自动推进**：合并后进入下一项。
