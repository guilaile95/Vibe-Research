# Chat 交接（可直接粘贴到新会话）

---

## 仓库与 Git

| 项 | 值 |
|----|-----|
| 仓库（origin） | https://github.com/guilaile95/Vibe-Research |
| 分支 | `feature/research-system-v01` |
| 当前 HEAD | 功能提交 `9932601`；文档刷新后以 `git rev-parse HEAD` 为准 |
| origin | `https://github.com/guilaile95/Vibe-Research.git` |
| upstream | `https://github.com/simonlin1212/Vibe-Research.git` |
| 跟踪 | `origin/feature/research-system-v01` |
| 工作区 | 接手后请先 `git status` / `git rev-parse HEAD` 复核 |

> 说明：拼写为 **guilaile95**（非 guiliale95）。

## 协作方式

- 本地个人 AI 投研看板：**FastAPI** + **React/Vite**
- 持仓、账户资金、模型 Key、复盘磁盘缓存在**用户目录 / localStorage**，不进 Git
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

- 每日复盘结构化聚合 + **九维 AI** 分析契约
- `GET /api/daily-review`：**SWR**（内存 + 磁盘 latest + 后台 single-flight 刷新）
- normal 不被坏 partial 覆盖；刷新失败可保留旧 normal
- 全 A 快照：东财**直连**、分页、页级重试、失败不半截
- `POST /api/portfolio/advice`：fresh 复盘、breadth unavailable → **503 fail-closed**
- 固定动作与比例档位；**validator 为执行字段权威**
- add：后端计算 `execution_quantity` 与 `estimated_amount`（`5dec970`）并已 E2E 验收
- 账户资金手工填写：`GET`/`PUT /api/account-profile`；**未接入**持仓建议
- **持仓支持新增、精确编辑和安全删除**（`9932601`，已浏览器验收）：
  - `POST` 新增：同代码仍**加权合并**
  - `PUT` 编辑：**精确替换** shares/cost（不加权、不 upsert）
  - 删除：确认弹窗 + 错误反馈；不写清仓记录
  - 数量输入：**不再静默转换**（如 `-100` 不会变 `100`）
  - 与 `account_profile` / advice 隔离
- 账户资金只读指标已接入持仓建议结果 (`account_funding` & `account_metrics`)；**尚未参与动作裁决**；可用现金约束留待下一阶段
- **持仓建议架构收口第一阶段完成**（`refactor/portfolio-advice-architecture-v01`）：
  - 建立公共契约 `portfolio_advice_contracts.py` 为策略常量唯一源
  - Validator 断开对 Prompt 的反向依赖，改从 Contracts 导入
  - 账户指标计算拆分为独立模块 `portfolio_advice_account_metrics.py`
  - Golden Tests (27 个场景快照) 确保重构过程 100% 行为不变

## 关键安全边界

- 持仓建议**禁止**使用 stale 磁盘复盘
- 不向客户端泄漏 ProxyError / 完整 URL / traceback
- 账户资金已可手工维护，但**建议链路仍未使用**总资产/可用现金
- 无可靠可卖数量 → reduce/sell 须人工确认
- 无 K 线不得编造技术位；不做 T
- add 比例 = **相对当前持股**，不是账户仓位/资金比例
- 真实 `portfolio.json` / `account_profile.json` **不得**用于自动化测试写入
- 持仓增删改**不**自动调用 `POST /api/portfolio/advice`

## 最近关键提交（节选）

- `67a1fc5` refactor: extract account funding metrics calculation to dedicated module
- `70d2a71` refactor: extract portfolio advice contracts as strategy constants single source of truth
- `9fa2428` test: add golden tests to lock portfolio advice validator behavior (27 scenarios)
- `5752845` feat: add read-only account metrics to portfolio advice
- `9932601` feat: add portfolio holding exact edit and delete confirm
- `f3d90af` harden account funding persistence
- `88a1f83` restore account funding profile UI
- `fe54b8f` add manual account funding input

## 当前下一任务

见 `docs/NEXT_TASK.md`：**待产品优先级确认**。
不得重复已完成的持仓编辑 / 账户资金手工维护；不得在未确认前接入「账户资金 → 持仓建议」。

## 已知测试例外

```text
tests/test_fixes.py::test_run_cli_stream_timeout
```

Windows 缺少 `python3` 命令，退出码 9009。勿把新失败归入此项。

## 给新会话的强制要求

1. 先读上述 `docs/*`，并用 `git log` / 代码路径核对，**不要凭记忆扩写事实**。
2. 先 `git status`、`git rev-parse HEAD`、`git remote -v`。
3. **不要重复**已在文档与提交中标明完成的大功能，除非验收失败需修复。
4. 未经用户确认，**不扩大任务范围**、不 force push、不改无关模块。

---

我接下来会发送 Codex 的执行结果。请先审查结果与仓库事实是否一致，不要重复已经完成的任务，也不要在我确认前扩大任务范围。
