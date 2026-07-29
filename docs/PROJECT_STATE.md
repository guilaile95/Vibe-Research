# 项目当前状态

> 文档基准：主分支 `feature/research-system-v01`；最新合并提交为 `30abb5b`（当前 HEAD 以 `git rev-parse HEAD` 为准）
> 仅描述仓库内已实现能力；不包含密钥、持仓内容或代理敏感配置。

## 1. 技术栈与数据存储

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind | 默认开发端口 `:5899`（`frontend/vite.config.ts`） |
| 后端 | FastAPI + Uvicorn | 默认 `:8900`（`backend` + README） |
| A 股数据 | `backend/astock.py` + 仓库内 `a-stock-data/` | 东财等公开接口；`em_get` 固定直连 |
| 全球指数/美港股子集 | `backend/gstock.py` + `global-stock-data/` | 复用 `astock.em_get` |
| 持仓 | `backend/portfolio.py` | 默认 `~/.vibe-research/portfolio.json`（`VR_DATA_DIR` 可覆盖） |
| 账户资金 (手工维护) | `backend/account_profile.py` | 默认 `~/.vibe-research/account_profile.json`（`VR_DATA_DIR` 可覆盖） |
| 交易流水 (P1-1/P1-2) | `backend/trade_ledger_store.py` | 默认 `VR_DATA_DIR/trade_ledger.sqlite3`（支持 `VIBE_RESEARCH_TRADE_LEDGER_DB` 覆盖） |
| 决策反馈 (P1-3) | `backend/decision_feedback_store.py` | 默认 `VR_DATA_DIR/decision_feedback.sqlite3`（支持 `VIBE_RESEARCH_DECISION_FEEDBACK_DB` 覆盖） |
| 复盘磁盘缓存 | `backend/daily_review_cache.py` | `daily_review_latest.json`（同上数据目录） |
| 复盘历史 | `review_store` / `review_history` | SQLite（如 Windows 下 `%LOCALAPPDATA%/VibeResearch/daily_reviews.sqlite3`） |
| 模型接入 | 前端 localStorage `vr-llm` + 后端 `chat` / `cli_runtime` | API 或本机 CLI 订阅；密钥不进仓库 |

版本线索：`frontend/package.json` 为 `0.1.3`；schema 如 `daily-review-v0.1`、`portfolio-advice-v0.1`。

## 2. 交易流水 (P1-1 / P1-2) 核心能力

- **后端存储与 API (PR #25，Merge SHA `bd0214a`)**:
  - 独立 SQLite 数据库 `trade_ledger.sqlite3`。
  - 数据模型包含计划价格/数量、实际价格/数量/成交时间、手续费/其他费用、未执行原因、备注、建议引用、Thesis 引用及派生财务指标（成交金额、总费用、净现金流、价格偏差、数量完成率）。
  - 支持交易创建 (`POST /api/trades`)、条件筛选查询 (`GET /api/trades`)、单条详情 (`GET /api/trades/{trade_id}`)、原子作废 (`POST /api/trades/{trade_id}/void`)。
  - `not_executed` 状态不写/不发实际成交字段；已作废记录不支持再次编辑或物理删除。
- **前端页面与交互 (PR #25)**:
  - 实现 `/trades` 页面，包含列表、多条件筛选、创建 Modal、详情 Modal（结构化展示 `advice_snapshot`）、作废确认 Modal 及分页控制。
  - 前端纯逻辑 `validateTradeDraft` 与 `buildTradeCreateInput` 保持与后端校验契约完全一致。

## 3. 决策反馈 (P1-3 MVP & Hardening)

- **PR #26 (P1-3 MVP 基础功能，Merge SHA `30abb5b`)**:
  - 建立独立 SQLite 数据库 `decision_feedback.sqlite3` 与 REST API。
  - 数据模型包含 `feedback_id`, `code`, `advice_trade_date`, `advice_generated_at`, `trade_id`, `adoption_status`, `outcome_status`, `note`, `created_at`, `voided_at`, `void_reason`。
  - 实现前端 `/decision-feedback` 页面与侧边栏导航「决策反馈」，支持列表、筛选、创建 Modal、详情 Modal、作废确认 Modal 及分页。
  - 在交易流水详情 Modal 中扩展只读跳转入口。
- **PR #27 (P1-3 Hardening 加固加固工程)**:
  - **严格请求契约 (`extra="forbid"`)**: 严格拦截未知顶层字段及未知 `advice_ref` 嵌套字段，非法请求统一返回 HTTP 422；禁止客户端指定 `feedback_id`, `created_at`, `voided_at`, `void_reason` 或废弃的顶层 `advice_trade_date`/`advice_generated_at`。
  - **全量 128-bit UUID**: 新生成标识升级为 `fb_` + 32 位 hex 字符串 (`uuid.uuid4().hex`)，同时向前兼容既有 12 位短 ID 的读取与作废。
  - **BEGIN IMMEDIATE 原子作废**: 存储层引入显式 SQLite 事务，多线程/多进程并发作废时精确返回 409 冲突，无 500 异常与数据损坏误报。
  - **来源数据零副作用隔离**: 单元测试中验证创建/作废反馈时 `review_history`, `trade_ledger`, `portfolio.json`, `account_profile.json` 保持只读且哈希不变。
  - **前端数据质量与错误路径 E2E**: 创建表单默认 `outcome_status = "not_evaluated"`；交易详情链接调整为「查看该股票反馈」；新增 Playwright `decision-feedback-failure.browser.mjs` 测试涵盖列表失败重试、创建 404/409/422 输入保留、详情失败展示、作废 409 Modal 不关闭及 HTML 错误隐藏。

## 4. 每日复盘 SWR 机制与九维结构

- **Stale-while-revalidate 展示路径**:
  1. 内存新鲜缓存 → 立即返回（`stale=false`）。
  2. 无内存但有磁盘「最近成功」包 → 返回旧结果（`stale=true`）并 single-flight 后台刷新。
  3. 皆无 → 同步抓取聚合。
- **normal / partial / unavailable 覆盖规则**:
  - 核心组件：`indices`、`breadth`、`emotion`、`industry_boards`、`concept_boards`。
  - 可选组件：`global_indices`、`turnover`、`region_boards`。
  - 关键组件 unavailable 的 partial / 整体 unavailable 不覆盖已有 normal 包。
- **全 A 快照抓取**:
  - `astock.a_share_snapshot`：东财 clist 分页；整页失败整体抛错，不返回已抓部分列表。
  - `em_get` 固定直连，`trust_env=False`，不读系统代理；同一页内有限重试。

## 5. 持仓建议 (Portfolio Advice) 机制与架构

- **请求与门禁**: `POST /api/portfolio/advice` 使用 fresh 复盘；`breadth unavailable` 时 **503 fail-closed** 并直接抛错不调用模型。
- **动作与比例档位**:
  - 动作：`add` / `hold` / `reduce` / `sell` / `watch` / `avoid`。
  - `execution_size_pct_of_holding` 为相对**当前持股数量**的比例。
  - `add` 建议由后端权威计算 `execution_quantity`（向下取整至 100 股整手，不足 100 股为 null）与 `estimated_amount`。
- **Validator 七阶段 Pipeline 与 Golden Tests**:
  - Validator 作为 Facade 兼容入口，内部按固定顺序执行：Schema → Legacy Compatibility → Fact Reconciliation → Policy Audit → Execution → Narrative Audit → Final Assembly。
  - `portfolio_advice_policy.py` 为投资政策唯一代码来源；Golden Tests 包含 27 个场景快照测试。
- **账户资金只读指标**: 账户资金手工维护（`account_profile.json`）仅在 Validator 完成后由 `portfolio_advice_account_metrics` 追加 `account_funding` 与 `account_metrics` 只读指标，不参与动作裁决、资金约束或 Prompt 构造。

## 6. 持仓手工维护 (新增 / 精确编辑 / 安全删除)

- `POST /api/portfolio/holding`：同代码加权合并成本。
- `PUT /api/portfolio/holding`：精确替换 shares/cost，不加权，code 不存在返回 404。
- 删除：前端二次确认弹窗，`DELETE` 仅移出持仓，不写清仓记录。
- 数量输入保留原始字符串，不静默转换负数。

## 7. 最近关键提交

| 短哈希 | 说明 |
|--------|------|
| `30abb5b` | Merge pull request #26 from guilaile95/feat/decision-feedback-mvp |
| `bd0214a` | Merge pull request #25 from guilaile95/feat/trade-ledger-frontend |
| `9932601` | feat: add portfolio holding exact edit and delete confirm |
| `0ee21aa` | refactor: split portfolio advice validator pipeline |

## 8. 已知测试例外

```text
backend/tests/test_fixes.py::test_run_cli_stream_timeout
```
Windows 环境缺少 `python3` 命令，实际测试输出 `fake 退出码 9009`，属于已知 Windows 环境兼容例外，不影响业务功能。
