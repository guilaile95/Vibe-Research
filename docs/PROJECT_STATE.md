# 项目当前状态

> 文档基准：主分支 `feature/research-system-v01`；最新合并提交为 `06594c2`（当前 HEAD 以 `git rev-parse HEAD` 为准）
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
| 决策依据 (P2-1) | `backend/decision_trace_store.py` | 默认 `VR_DATA_DIR/decision_trace.sqlite3`（支持 `VIBE_RESEARCH_DECISION_TRACE_DB` 覆盖） |
| 复盘磁盘缓存 | `backend/daily_review_cache.py` | `daily_review_latest.json`（同上数据目录） |
| 复盘历史 | `review_store` / `review_history` | SQLite（如 Windows 下 `%LOCALAPPDATA%/VibeResearch/daily_reviews.sqlite3`） |
| 模型接入 | 前端 localStorage `vr-llm` + 后端 `chat` / `cli_runtime` | API 或本机 CLI 订阅；密钥不进仓库 |

版本线索：`frontend/package.json` 为 `0.1.3`；schema 如 `daily-review-v0.1`、`portfolio-advice-v0.1`。

## 2. 信号账本与流水 (P2-2 Signal Ledger) 核心能力

- **后端存储与 API (P2-2)**:
  - 复用/扩展 SQLite 数据库 `decision_trace.sqlite3`，新增 `signal_entries` 与 `decision_outcomes` 数据表及高效索引。
  - 完整记录决策管道 7 大阶段 (`schema`, `compatibility`, `fact_reconciliation`, `policy_audit`, `execution`, `narrative_audit`, `account_constraint`) 的中间信号与警告/错误事件。
  - 自动提取并持久化个股最终决策裁决结果 (`decision_outcomes`)、目标仓位及应用的约束规则列表。
  - 提供只读 REST API：`GET /api/signal-ledger` (支持 `decision_run_id`, `stage`, `code`, `severity` 筛选与分页) 和 `GET /api/signal-ledger/run/{decision_run_id}` (获取完整运行时间线)。
- **前端页面与交互 (P2-2)**:
  - 新增 `/signal-ledger` 信号账本页面与侧边栏导航「信号账本」。
  - 包含决策 Run 元信息卡片、最终裁决结果网格卡片及 7 阶段流水节点时间线。
  - 支持多条件筛选、状态徽章、JSON 结构化载荷展平与参数回显。
- **验证**:
  - 后端信号账本测试 7 passed；后端 not-live 全量测试连续两次 **1606 passed, 0 failed**；前端 214 单测全部通过；Vite 生产构建成功；Playwright 真实 FastAPI E2E `signal-ledger-real.browser.mjs` 通过。

## 2. 账户资金执行策略 (P2-3 Account Capital Constraints) 核心能力

- **后端策略与约束 (P2-3)**:
  - 新增独立策略文件 `account_execution_policy.py`，五字段策略：`lot_size`、`min_cash_reserve_pct`、`max_single_stock_allocation_pct`、`tie_breaker_order`、`allow_partial_execution`。
  - 策略文件持久化于 `VR_DATA_DIR/account_execution_policy.json`，原子写入、线程安全、校验回退默认值。
  - `portfolio_advice_cash_constraint.py` 改用策略中的 `lot_size` 进行整手取整；多笔加仓继续 fail-safe 全部 null。
  - 提供 REST API：`GET /api/account-execution-policy`、`PUT /api/account-execution-policy`（校验失败 → 400）。
- **前端页面与交互 (P2-3)**:
  - 新增 `/account-policy` 策略编辑器页面与侧边栏导航「执行策略」。
  - 五字段表单编辑，% 字段 ×100 显示 /100 存储，保存/重置/反馈。
- **验证**:
  - 后端策略专项测试 11 passed；全量后端测试全绿。

## 3. 决策依据层 (P2-1 Evidence Layer) 核心能力

- **后端存储与 API (P2-1)**:
  - 独立 SQLite 数据库 `decision_trace.sqlite3`（包含 `decision_runs`, `evidence_items`, `explanation_items` 数据表与索引）。
  - `decision_run_id` 使用确定性算法派生：`"dr_" + sha256("portfolio_advice\n{trade_date}\n{generated_at}")`。
  - 持仓建议成功生成后自动抓取归档多维度证据 (market, sector, stock, portfolio, account, risk) 与规则推演链。归档异常时记录 `failed` 追踪状态，不阻断主建议接口。
  - 提供只读 REST API：`GET /api/decision-evidence`, `GET /api/decision-evidence/{decision_run_id}`, `GET /api/decision-evidence/by-advice`。禁止客户端修改或注入证据数据。
- **前端页面与交互 (P2-1)**:
  - 新增 `/decision-evidence` 决策依据看板与侧边栏导航「决策依据」。
  - 具备列表筛选、数据质量/追踪状态标识、运行详情 Modal（呈现结构化证据卡片、推演结论与支持/限制证据关联及缺失数据提示）。
  - 持仓建议结果打通「查看决策依据」只读跳转入口。
- **验证**:
  - 后端决策依据专项测试 15 passed；前端单元测试 207 passed；Vite 构建成功；Playwright 真实 FastAPI E2E 全流程通过。

## 4. 决策反馈分析 (P2-4A Feedback Analytics) 核心能力

- **后端只读聚合 (P2-4A)**:
  - 新增 `decision_analytics_service.py`，只读聚合 `decision_feedback` 表（`mode=ro` + `PRAGMA query_only=ON`）。
  - `get_adoption_summary`: 四类 adoption_status 分布 + `adoption_rate`（`(followed + partially_followed) / total`，分母 0 返回 null）。
  - `get_outcome_summary`: 四类 outcome_status 分布 + `positive_rate`（`(better + as_expected) / (total - not_evaluated)`）。
  - `get_stock_summary`: 按 code `GROUP BY`，单次 SQL `CASE WHEN` 聚合，按 total DESC。
  - 提供 REST API：`GET /api/decision-analytics/{adoption,outcome,stocks}`。
- **前端页面与交互 (P2-4A)**:
  - 新增 `/decision-performance` 决策绩效看板与侧边栏导航「决策绩效」。
  - 采纳率卡片 + 结果分布卡片 + 个股绩效表，日期区间过滤。
- **验证**:
  - 后端分析专项测试 20 passed；全量后端测试全绿。

## 5. 收益归因 (P2-4B Performance Attribution) 核心能力

- **后端归因计算 + 快照 (P2-4B)**:
  - 独立 SQLite 库 `performance_attribution.sqlite3`（`VIBE_RESEARCH_PERFORMANCE_ATTRIBUTION_DB` 可覆盖）。
  - `performance_attribution_service.py` 加权平均成本法，从交易流水确定性计算实现盈亏，零网络请求。
  - 超卖按可用数量计算并标注 limitation；无持仓成本基准的卖出不计入实现盈亏。
  - `unrealized_pnl` 仅在显式传入 `price_map` 时计算，否则为 null + limitation（不虚构现价）。
  - 提供 REST API：`GET /api/performance-attribution`（实时计算）、`POST /api/performance-attribution/snapshot`（冻结快照）、`GET /api/performance-attribution/snapshots`、`GET /api/performance-attribution/snapshots/{id}`。
- **前端页面与交互 (P2-4B)**:
  - 新增 `/performance-attribution` 收益归因看板与侧边栏导航「收益归因」。
  - 合计卡片 + 逐股归因表 + 历史快照列表，盈亏正负配色，null 显示 `—`。
- **验证**:
  - 后端归因专项测试 24 passed；全量后端测试全绿。

## 6. 交易流水 (P1-1 / P1-2) 核心能力

- **后端存储与 API (PR #25，Merge SHA `bd0214a`)**:
  - 独立 SQLite 数据库 `trade_ledger.sqlite3`。
  - 支持交易创建 (`POST /api/trades`)、条件筛选查询 (`GET /api/trades`)、单条详情 (`GET /api/trades/{trade_id}`)、原子作废 (`POST /api/trades/{trade_id}/void`)。
- **前端页面与交互 (PR #25)**:
  - 实现 `/trades` 页面，包含列表、多条件筛选、创建 Modal、详情 Modal、作废确认 Modal 及分页控制。

## 7. 决策反馈 (P1-3 MVP & Hardening)

- **PR #26 (P1-3 MVP) & PR #27 (P1-3 Hardening，Merge SHA `dedf99b`)**:
  - 独立 SQLite 数据库 `decision_feedback.sqlite3`。
  - 严格 Pydantic 契约 (`extra="forbid"`)，全量 128-bit UUID 标识 (`fb_` + 32 位 hex)，`BEGIN IMMEDIATE` 显式事务原子作废。
  - 前端 `/decision-feedback` 页面，支持列表、筛选、创建、详情与作废全流程，默认 `outcome_status = "not_evaluated"`。

## 8. 每日复盘 SWR 机制与九维结构

- **Stale-while-revalidate 展示路径**: 内存新鲜缓存 → 磁盘最近成功包 (stale) + single-flight 后台刷新 → 同步抓取聚合。
- **normal / partial / unavailable 覆盖规则**: 关键组件 unavailable 不覆盖已有 normal 包。

## 9. 持仓建议架构

- Validator 采用固定七阶段 Pipeline（Schema → Compatibility → Fact Reconciliation → Policy Audit → Execution → Narrative Audit → Final Assembly）。
- `portfolio_advice_policy.py` 为投资政策唯一代码来源；27 个 Golden Tests 场景锁定输出规范。

## 10. 最近关键提交

| 短哈希 | 说明 |
|--------|------|
| `06594c2` | Merge pull request #32 from guilaile95/feat/performance-attribution |
| `24117d6` | Merge pull request #31 from guilaile95/feat/decision-feedback-analytics |
| `ecd101b` | Merge pull request #30 from guilaile95/feat/account-capital-constraints |
| `eecbf56` | Merge pull request #29 from guilaile95/feat/signal-ledger |
| `dedf99b` | Merge pull request #27 from guilaile95/fix/decision-feedback-hardening |
| `30abb5b` | Merge pull request #26 from guilaile95/feat/decision-feedback-mvp |
| `bd0214a` | Merge pull request #25 from guilaile95/feat/trade-ledger-frontend |
