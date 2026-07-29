# Chat 交接（可直接粘贴到新会话）

---

## 仓库与 Git

| 项 | 值 |
|----|-----|
| 仓库（origin） | https://github.com/guilaile95/Vibe-Research |
| 主分支 | `feature/research-system-v01` |
| 最新合并提交 | `06594c2` (`Merge pull request #32 from guilaile95/feat/performance-attribution`)；当前 HEAD 以 `git rev-parse HEAD` 为准 |
| 工作区 | 接手后请先 `git status` / `git rev-parse HEAD` 复核 |

> 说明：拼写为 **guilaile95**（非 guiliale95）。

## 协作方式

- 本地个人 AI 投研看板：**FastAPI** + **React/Vite**
- 持仓、账户资金、模型 Key、复盘磁盘缓存在**用户目录 / localStorage / VR_DATA_DIR**，不进 Git
- 业务改动优先有测试；`pytest -m "not live"`；前端 `npm run build`
- 禁止把密钥、代理订阅、真实持仓写入仓库或对话日志
- **测试通过 ≠ 功能通过**：交互类改动须真实浏览器 / Playwright 验收

## 请先阅读的文档（本仓库 `docs/`）

1. `docs/PROJECT_STATE.md` — 已完成能力与关键提交
2. `docs/ARCHITECTURE.md` — 复盘、持仓建议、持仓维护调用链
3. `docs/DECISIONS.md` — 设计决定
4. `docs/KNOWN_ISSUES.md` — 限制与已知测试例外
5. `docs/NEXT_TASK.md` — **当前下一任务**

## 已完成能力（摘要）

- **P2-1 决策依据层 (Decision Evidence Layer)**（已完成）：
  - 独立 `decision_trace.sqlite3` 数据库与 REST API (`/api/decision-evidence`)
  - 确定性 `decision_run_id` 衍生算法 (`dr_` + sha256)
  - 自动化归档结构化事实证据 (market, sector, stock, portfolio, account, risk) 与规则推演链
  - 前端 `/decision-evidence` 探索看板，支持筛选、运行详情、支持/限制证据关联与可视化展示
  - 持仓建议结果打通「查看决策依据」只读跳转入口
- **P2-2 信号账本 (Signal Ledger)**（已完成）：
  - 扩展 `decision_trace.sqlite3`，新增 `signal_entries` 与 `decision_outcomes` 数据表
  - REST API: `GET /api/signal-ledger`, `GET /api/signal-ledger/run/{decision_run_id}`
  - 前端 `/signal-ledger` 信号账本页面与 7 阶段流水时间线
- **P2-3 账户资金执行策略 (Account Capital Constraints)**（已完成）：
  - 独立策略文件 `account_execution_policy.py`，五字段策略持久化于 `VR_DATA_DIR`
  - REST API: `GET/PUT /api/account-execution-policy`
  - 前端 `/account-policy` 策略编辑器
- **P2-4A 决策反馈分析 (Feedback Analytics)**（已完成）：
  - 只读聚合 `decision_feedback` 表，三端点 `/api/decision-analytics/{adoption,outcome,stocks}`
  - 前端 `/decision-performance` 决策绩效看板
- **P2-4B 收益归因 (Performance Attribution)**（已完成）：
  - 独立 `performance_attribution.sqlite3`，加权平均成本法四端点
  - 前端 `/performance-attribution` 收益归因看板
- **P1-1 & P1-2 交易流水 (Trade Ledger)**（已合并，PR #25，Merge SHA `bd0214a`）
- **P1-3 决策反馈 (Decision Feedback)**（已合并，PR #26 & #27，Merge SHA `dedf99b`）

## 关键安全边界

- 持仓建议**禁止**使用 stale 磁盘复盘；`breadth unavailable` 必须 **503 fail-closed**
- 账户资金手工维护已接入只读指标，但**建议裁决链路仍未接入**总资产/可用现金限制
- 无可靠可卖数量 → `reduce`/`sell` 须人工确认
- 无 K 线不得编造技术位；不做 T（无 `t_trade`）
- `add` 比例为**相对当前持股数量**，不是账户仓位/资金比例
- 真实 `portfolio.json` / `account_profile.json` **不得**用于自动化测试写入
- 决策依据层、决策反馈与交易流水采用独立 SQLite 数据库存储，严禁修改既有 `portfolio.json` 或 `review_history`
- 不向客户端泄漏 ProxyError / 完整 URL / traceback / SQL 语句
- 明确不做：收益率计算、建议准确率、模型训练、自动调权、自动归因

## 已知测试例外

```text
backend/tests/test_fixes.py::test_run_cli_stream_timeout
```
Windows 环境缺少 `python3` 命令，实际错误为 `fake 退出码 9009`。

## 当前下一任务

Scheduler import 测试顺序隔离修复（`fix/scheduler-test-isolation`）。
`backend/tests/test_scheduler_lifespan.py::test_import_app_does_not_start_scheduler` 原方案依赖当前 pytest 进程全局线程状态，导致测试间顺序依赖；改为独立 `sys.executable` 子进程验证 `import app`，不修改 Scheduler 产品逻辑。
