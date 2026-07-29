# Chat 交接（可直接粘贴到新会话）

---

## 仓库与 Git

| 项 | 值 |
|----|-----|
| 仓库（origin） | https://github.com/guilaile95/Vibe-Research |
| 主分支 | `feature/research-system-v01` |
| 最新合并提交 | `30abb5b` (`Merge pull request #26 from guilaile95/feat/decision-feedback-mvp`)；当前 HEAD 以 `git rev-parse HEAD` 为准 |
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

- **P1-1 & P1-2 交易流水 (Trade Ledger)**（已完成，PR #25，Merge SHA `bd0214a`）：
  - 独立 `trade_ledger.sqlite3` 数据库与 REST API (`/api/trades`)
  - 实现 `/trades` 前端页面（列表、条件筛选、新建、详情结构化展示 `advice_snapshot`、作废及分页）
  - 前端纯逻辑与后端契约完全对齐，`not_executed` 状态不发成交字段
- **P1-3 决策反馈 (Decision Feedback MVP & Hardening)**（MVP 已合并 PR #26；Hardening 已完成 PR #27）：
  - 独立 `decision_feedback.sqlite3` 数据库与 REST API (`/api/decision-feedback`)
  - 严格 Pydantic 契约 (`extra="forbid"`)，只允许规范请求字段，拒绝顶层未知字段及未知嵌套 `advice_ref`
  - 全量 128-bit UUID 标识与 `BEGIN IMMEDIATE` 显式 SQLite 事务原子作废 (200/409)
  - 来源数据库零副作用隔离（建议库、交易库、`portfolio.json` 与 `account_profile.json` 保持严格只读）
  - 数据库损坏 Fail-Closed 防护，返回 HTTP 500
  - 前端 `/decision-feedback` 页面与导航支持、`not_evaluated` 默认结果、Playwright 真实/错误路径双 E2E 测试全过
- **每日复盘九维结构 + GET /api/daily-review SWR 缓存机制**
- **持仓支持新增、精确编辑和安全删除**（`9932601`）
- **持仓建议 Validator 拆分与 Golden 测试套件**（`0ee21aa`）

## 关键安全边界

- 持仓建议**禁止**使用 stale 磁盘复盘；`breadth unavailable` 必须 **503 fail-closed**
- 账户资金手工维护已接入只读指标，但**建议裁决链路仍未接入**总资产/可用现金限制
- 无可靠可卖数量 → `reduce`/`sell` 须人工确认
- 无 K 线不得编造技术位；不做 T（无 `t_trade`）
- `add` 比例为**相对当前持股数量**，不是账户仓位/资金比例
- 真实 `portfolio.json` / `account_profile.json` **不得**用于自动化测试写入
- API 请求严格拦截未在 Schema 中定义的顶层及嵌套未知字段 (HTTP 422)
- 决策反馈与交易流水采用独立 SQLite 数据库存储，严禁修改既有 `portfolio.json` 或 `review_history`
- 不向客户端泄漏 ProxyError / 完整 URL / traceback / SQL 语句
- 明确不做：收益率计算、建议准确率、模型训练、自动调权、自动归因

## 已知测试例外

```text
backend/tests/test_fixes.py::test_run_cli_stream_timeout
```
Windows 环境缺少 `python3` 命令，实际错误为 `fake 退出码 9009`。

## 当前下一任务

见 `docs/NEXT_TASK.md`：**下一产品任务待优先级确认**。
不得自行启动账户资金参与动作裁决、Explainability、Evidence Layer、Signal Ledger、收益归因、模型训练或自动调权。

## 给新会话的强制要求

1. 先读上述 `docs/*`，并用 `git log` / 代码路径核对，**不要凭记忆扩写事实**。
2. 先 `git status`、`git rev-parse HEAD`、`git remote -v`。
3. **不要重复**已在文档与提交中标明完成的大功能。
4. 未经用户确认，**不扩大任务范围**、不 force push、不改无关模块。
