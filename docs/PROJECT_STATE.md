# 项目当前状态

> 文档基准：分支 `feature/research-system-v01`；最新合并提交为 `30abb5b`（当前 HEAD 以 `git rev-parse HEAD` 为准）
> 仅描述仓库内已实现能力；不包含密钥、持仓内容或代理敏感配置。

## 1. 技术栈与数据存储

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind | 默认开发端口 `:5899`（`frontend/vite.config.ts`） |
| 后端 | FastAPI + Uvicorn | 默认 `:8900`（`backend` + README） |
| A 股数据 | `backend/astock.py` + 仓库内 `a-stock-data/` | 东财等公开接口；`em_get` 固定直连 |
| 全球指数/美港股子集 | `backend/gstock.py` + `global-stock-data/` | 复用 `astock.em_get` |
| 持仓 | `backend/portfolio.py` | 默认 `~/.vibe-research/portfolio.json`（`VR_DATA_DIR` 可覆盖） |
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
- **验证**:
  - 单元与集成测试 178 passed；Pytest 离线回归 1505 passed；Playwright E2E 真实 FastAPI 隔离验证通过。

## 3. 决策反馈 (P1-3) 核心能力

- **后端存储与 API (PR #26，Merge SHA `30abb5b`)**:
  - 独立 SQLite 数据库 `decision_feedback.sqlite3`。
  - 严格 Pydantic 契约 (`extra="forbid"`)，只允许规范请求字段，拒绝顶层或嵌套未知字段（HTTP 422）。
  - 必须提供嵌套 `advice_ref: { trade_date, generated_at }` 并由后端只读核验；可选 `trade_id` 由后端核验。
  - 生成 `fb_` + 32 位全量 UUID 标识 (`uuid.uuid4().hex`)，并兼容历史 12 位 ID 的读取与作废。
  - `BEGIN IMMEDIATE` 显式 SQLite 事务实现原子并发作废。
  - 数据库损坏 Fail-Closed 机制，返回安全 HTTP 500 提示 `{"detail": "决策反馈数据损坏，已停止读写"}`。
- **前端页面与交互 (PR #26)**:
  - 实现 `/decision-feedback` 页面与侧边栏导航「决策反馈」。
  - 表单默认 `outcome_status = "not_evaluated"`。
  - 支持多条件筛选、新建 Modal、详情 Modal、作废确认 Modal 及分页。
  - 交易详情 Modal 提供「查看该股票反馈」跳转链接。
- **验证**:
  - 后端决策反馈专项测试 24 passed；前端单元测试 192 passed；前端 Vite Build 构建成功；Playwright 真实 FastAPI E2E 与模拟错误路径 E2E 全过。

## 4. 每日复盘九维结构

- **客观数据包**（`generate_daily_review`，schema `daily-review-v0.1`）主要包含：
  - `data_health.components`：indices / global_indices / breadth / emotion / turnover / industry_boards / concept_boards / region_boards
  - `market_environment`：indices、global_indices、breadth
  - `sector_rotation`：industry / concept / region + highlights
  - `short_term_emotion`
  - `capital_activity`
  - 顶层 `status`：`normal` | `partial` | `unavailable`
- **AI 分析输出**（`daily_review_ai_prompt.NINE_DIMENSION_HEADINGS`）固定九个二级标题：
  1. 市场整体
  2. 市场情绪与赚钱效应
  3. 涨停结构
  4. 主线题材
  5. 核心与高活跃个股
  6. 催化与公开信息
  7. 盘面本质与风险状态
  8. 明日观察点
  9. 复盘总结

## 5. GET `/api/daily-review`

- 定义：`backend/app.py` → `daily_review_snapshot`
- 调用：`daily_review.get_daily_review_for_display()`
- 响应：`{ "data": <复盘包>, "cache_meta"?: { source, stale, refreshing, saved_at, age_seconds, refresh_failed, refresh_error } }`
- `normal` / `partial` / `unavailable` 均为 HTTP 200；聚合逃逸异常 → 502
- **不接受** date/refresh 查询参数；不做历史日期查询

## 6. POST `/api/portfolio/advice`

- 链路：`get_portfolio` → `generate_daily_review`（**fresh**）→ context → prompt → 模型 → `validate_portfolio_advice`
- 请求：`user_request?` + `llm`（`LLMConfig`）；**禁止**客户端注入 portfolio/context/messages
- 状态码：空持仓 409；广度不可用等市场核心数据 503；模型/输出无效 502；参数 400；其它 500

## 7. 最近关键提交（须与 `git log` 一致）

| 短哈希 | 说明 |
|--------|------|
| `30abb5b` | Merge pull request #26 from guilaile95/feat/decision-feedback-mvp |
| `b2f32b3` | feat(frontend): add decision feedback workflow |
| `75a47ee` | feat(feedback): add decision feedback storage and API |
| `bd0214a` | Merge pull request #25 from guilaile95/feat/trade-ledger-frontend |
| `60d22ac` | chore: remove legacy project author metadata |
| `718cf17` | feat(frontend): add trade ledger workflow |
| `9932601` | feat: add portfolio holding exact edit and delete confirm |
| `0ee21aa` | refactor: split portfolio advice validator pipeline |

## 8. 远程协作

- origin：`https://github.com/guilaile95/Vibe-Research.git`
- 主分支：`feature/research-system-v01`
