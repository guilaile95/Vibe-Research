# Chat 交接（可直接粘贴到新会话）

> 接手前先阅读根目录 `AGENTS.md`。

---

## 仓库与 Git

| 项 | 值 |
|----|-----|
| 仓库（origin） | https://github.com/guilaile95/Vibe-Research |
| 主分支 | `feature/research-system-v01` |
| 稳定功能基线 | 以 `git rev-parse origin/feature/research-system-v01` 为准；当前稳定 Head 见 docs/PROJECT_STATE.md（唯一权威） |
| 实时稳定 HEAD | 运行 `git rev-parse origin/feature/research-system-v01` |
| 产品候选池 | `docs/PRODUCT_BACKLOG.md`，由 PR #34 引入 |
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
6. `docs/PRODUCT_BACKLOG.md` — 长期产品候选池（BK-01 ~ BK-11）
7. `docs/GOVERNANCE.md` — 治理契约（权威链、CI 分级、分支保护、PR 恢复方案）
8. `docs/research/EXECUTION_STATE.md` — BK-11 历史执行记录，**非当前状态权威**（当前状态以 PROJECT_STATE.md 为准）

## 已完成能力（摘要）

- **P2-1 决策依据层 (Decision Evidence Layer)**（已上线，PR #28 / `fe954a78`）
- **P2-2 信号账本 (Signal Ledger)**（已上线，PR #29 / `eecbf56`）
- **Decision Trace 生产契约修复**（已上线，PR #35 / `f5f4206`）：
  - 权威字段：`holdings` / `account_funding` / `market_status`
  - 统一 `normalize_execution_size_pct()`；非法比例不进入 Outcome/Signal/Evidence payload
  - 缺失 `trade_date`/`generated_at` → `missing_decision_identity` 失败关闭
  - 历史错误归档**不回填**
- **P2-3 账户资金执行策略**（PR #30 / `ecd101b`）
- **P2-4A 决策反馈分析**（PR #31 / `24117d6`）
- **P2-4B 收益归因**（PR #32 / `06594c2`）
- **P1-1 & P1-2 交易流水**（PR #25 / `bd0214a`）
- **P1-3 决策反馈**（PR #26 & #27 / `dedf99b`）
- **北向资金（HKEX 官方日统计）**（已上线，PR #40）：`GET /api/market/northbound`；日级成交额/成交笔数/ETF 成交额/额度余额/活跃股；HKEX 不发布买卖拆分，净买入字段固定 None + limitation 说明
- **BK-11 阶段合并摘要**：技术指标与价格触发（PR #41）、shadow top-risk（PR #42）、BK-11 纯计算链（PR #44）、BK-11 历史（PR #45）、BK-11 输入审计 **BLOCKED**（PR #46 → Issue #48 已暂停/归档）

## 关键安全边界

- 持仓建议**禁止**使用 stale 磁盘复盘；`breadth unavailable` 必须 **503 fail-closed**
- 账户资金手工维护已接入只读指标与执行策略（`account_execution_policy`）；`add` 金额受可用现金安全垫与整手约束（P2-3）
- 无可靠可卖数量 → `reduce`/`sell` 须人工确认
- 无 K 线不得编造技术位；不做 T（无 `t_trade`）
- `add` 比例为**相对当前持股数量**，不是账户仓位/资金比例
- 真实 `portfolio.json` / `account_profile.json` **不得**用于自动化测试写入
- 决策依据层、决策反馈与交易流水采用独立 SQLite 数据库存储，严禁修改既有 `portfolio.json` 或 `review_history`
- 不向客户端泄漏 ProxyError / 完整 URL / traceback / SQL 语句
- 明确不做：收益率计算、建议准确率、模型训练、自动归权

## 已知测试例外

```text
backend/tests/test_fixes.py::test_run_cli_stream_timeout
```
Windows 环境缺少 `python3` 命令，实际错误为 `fake 退出码 9009`。

## 当前下一任务

当前阶段：Project Governance Consolidation v0.1（治理收口，非产品任务）；已授权产品任务：无。BK-11 已暂停（Issue #48）。

## 本地目录

本地 worktree/目录状态以 `git worktree list` 现场核验为准。
