# Vibe-Research Code Wiki

> 本文档是对仓库代码的结构化说明，作为工程 Wiki 使用。回答“这个仓库有什么、各部分做什么、如何运行、如何测试、数据存在哪里”。
>
> - 事实依据：仓库当前代码（stable 分支 `feature/research-system-v01` 工作树）。
> - 项目总体状态：[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)；产品方向：[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)；调用链细节：[`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。
> - 统计口径：backend 根目录 123 个 `.py` 文件，backend/tests 135 个 `.py`（133 个测试 + conftest + fixtures），全仓库约 259 个 Python 文件（不含 `.venv`）。

---

## 1. 项目概览

**产品定位**：Single-user Personal Local Investment OS —— 个人、本地的 A 股投资研究与决策辅助系统（非自动交易、非荐股）。

**核心使命**：围绕真实持仓与拟交易标的，减少买入、持有、卖出中的错误决策风险，同时改善长期收益。

**信息流主线**：

```text
市场与数据（astock/market/gstock/北向/资金面/资讯）
    ↓
研究、Thesis 与 Evidence（evidence_thesis_* / sector_research / myreports）
    ↓
信号和决策记录（decision_cockpit / signal_ledger / decision_evidence）
    ↓
持仓、账户与执行约束（portfolio / account_profile / account_execution_policy / cash_event / campaign）
    ↓
交易、结果、反馈与收益归因（trade_ledger / decision_feedback / performance_attribution）
```

**工程原则**（见根目录 [`AGENTS.md`](../AGENTS.md)）：deterministic-first —— 确定性层负责事实、校验、账本、硬风险与状态转移；AI 层只负责推理、解释、挑战与提议，不得绕过 Hard Risk、修改事实或自动交易。

---

## 2. 技术栈与依赖

### 2.1 分层技术栈

| 层 | 技术 | 版本/说明 |
|---|---|---|
| 前端 | React + TypeScript + Vite + Tailwind | React 19、Vite 6、Tailwind 3.4、ECharts 6、zustand、react-router-dom 7 |
| 后端 | FastAPI + Uvicorn | FastAPI ≥0.110、Python 3.11（Linux）/ 3.12（Windows） |
| 结构化存储 | SQLite（多库，见 §6）+ JSON 文件 | `sqlite3` 标准库直连，无 ORM |
| 数据湖 | DuckDB + Parquet | `limit_up_shadow` / `fact_lake_store`（影子湖，非生产路由） |
| 可选数据依赖 | akshare / mootdx / pandas | 未安装时对应端点返回 501，不影响核心 |
| 数据获取 | requests（东财/腾讯/百度等直连 HTTP） | 东财接口内置串行限流 `em_get` |

### 2.2 后端核心依赖（`backend/requirements.txt`）

```text
fastapi>=0.110      # Web 框架
uvicorn[standard]   # ASGI 服务器
requests            # 行情/研报等 HTTP 数据获取
duckdb>=1.4,<2      # 事实湖查询（影子能力）
akshare>=1.10       # 可选：一致预期/新闻/公告/财务
mootdx>=0.10        # 可选：K线/财务
pandas              # 可选：akshare 配套
```

依赖锁文件（权威来源为 lock 而非 requirements）：

| 平台 | 锁文件 | 说明 |
|---|---|---|
| Linux / CI | `requirements-linux-py311.lock.txt` | runtime |
| Linux / CI | `requirements-dev-linux-py311.lock.txt` | runtime + dev（pytest 等） |
| Windows | `requirements-dev-windows-py312.lock.txt` | Windows 权威锁（含运行与开发） |

锁文件由 `requirements-tooling.txt`（piptools）在 CI 中重新编译比对，保证可复现。

### 2.3 前端依赖（`frontend/package.json`）

运行时：`echarts`（图表）、`lucide-react`（图标）、`react` 19、`react-markdown` + `remark-gfm`、`react-router-dom` 7、`sonner`（toast）、`zustand`（状态）。

开发：`typescript`、`vite`、`tailwindcss`、`playwright`（E2E）、`@vitejs/plugin-react`。

---

## 3. 整体架构

### 3.1 进程与端口

```text
┌──────────────────────────────────────────────────────────────┐
│ Browser (前端 SPA)                                           │
│   frontend/  React 19 + Vite dev server  :5899               │
│   /api/* 由 vite 代理 →  http://127.0.0.1:8900               │
└──────────────────────────────┬───────────────────────────────┘
                               │ /api/* (REST / NDJSON 流式)
┌──────────────────────────────▼───────────────────────────────┐
│ backend/app.py  FastAPI + Uvicorn  :8900                      │
│   ├─ 核心业务端点（app.py 内联定义）                           │
│   ├─ 20+ 独立 Router（include_router 挂载）                   │
│   ├─ 全局异常处理器（corrupted → 500 安全文案）               │
│   ├─ 可选 API Key 中间件（VR_API_KEY）                        │
│   └─ lifespan：启动持仓行情刷新调度器（1800s）                 │
└──────────────────────────────┬───────────────────────────────┘
                               │
      ┌────────────┬───────────┴────────────┬────────────────┐
      ▼            ▼                        ▼                ▼
  公开数据源       SQLite 多库              JSON 文件         AI 通道
  (腾讯/东财/       (trade_ledger、          (portfolio.json、  (OpenAI 兼容
  百度/akshare/    daily_reviews、           account_profile、  API 或本机
  mootdx/北向/     decision_trace、          watchlist.json、   CLI cli-*)
  RSS/巨潮)        evidence_thesis、         研报文件、事件日志)
                   campaigns、alert_rules、
                   decision_feedback、
                   performance_attribution、
                   short_term_facts、
                   intel_digest、fact_lake)
```

### 3.2 分层设计

| 层 | 代表模块 | 职责 |
|---|---|---|
| **API / Router 层** | `app.py`、各 `*_router.py` | HTTP 契约、参数校验、异常映射为固定 HTTP 码 |
| **Service 层** | `*_service.py` | 业务编排：跨模块调用、AI 调用、策略应用 |
| **Domain / 确定性层** | `portfolio_advice_policy`、`portfolio_advice_pipeline`、`short_term_*`、`technical_indicators`、`decision_cockpit_signals`、`top_risk_evaluators` | 纯计算、事实重建、政策审计，无 IO 无 AI |
| **Store 层** | `*_store.py` | SQLite / JSON 持久化，WAL、事务、乐观锁、fail-closed 校验 |
| **AI 接入层** | `chat.py`、`cli_runtime.py`、`mcp_server.py` | OpenAI 兼容流式 / 本机 CLI 调用 / MCP 工具 |
| **数据获取层** | `astock.py`、`market.py`、`gstock.py`、`newsradar.py`、`northbound_capital_flow.py` | 外部源抓取、限流、缓存、降级信封 |

### 3.3 确定性 / AI 边界

```
确定性层（可信）          AI 层（辅助，不可信）
──────────────            ───────────────────
facts、validation         reasoning、explanation
freshness、account        challenge、synthesis
mechanics、hard risk      proposal
state transition
action envelope
portfolio_advice_pipeline 七阶段固定校验  ←  AI 的 add/hold/reduce 语义输出
portfolio_advice_policy   投资政策唯一来源  →  被 pipeline 审计、被 prompt 引用
```

关键体现：`portfolio_advice_validator` 是兼容 Facade，实际校验由 `portfolio_advice_pipeline` 七阶段执行；模型输出的数量/金额**不可信**，由 `portfolio_advice_execution` 重算；账户资金**不进入**模型输入与 Prompt。

---

## 4. 目录结构

```text
Vibe-Research/
├── AGENTS.md                  # 工程执行规则（源 of truth：执行纪律）
├── backend/                   # FastAPI 后端（核心，123 个 .py）
│   ├── app.py                 # 主应用：路由/异常/中间件/lifespan
│   ├── *.py                   # 业务模块（见 §5）
│   ├── tests/                 # 133 个 pytest 测试 + fixtures
│   ├── requirements*.txt      # 依赖与平台锁文件
│   ├── data/                  # 交易日历 JSON
│   └── .env.example           # 环境变量样例
├── frontend/                  # React SPA（React 19 + Vite + Tailwind）
│   ├── src/pages/             # 30 个页面组件
│   ├── src/components/        # 通用/布局/市场/板块/股票 UI 组件
│   ├── src/lib/               # API 客户端与视图模型（api.ts、各 *View.ts）
│   ├── src/data/sectorResearch/  # 板块研究静态数据（按行业分组）
│   ├── src/stores/            # zustand 状态（AI 任务/建议请求协调）
│   ├── tests/                 # Node 单测 + Playwright E2E
│   └── vite.config.ts         # :5899 端口、/api 代理、chunk 拆分
├── a-stock-data/              # A 股数据工具箱 SKILL（43 端点，独立使用）
├── global-stock-data/         # 全球市场数据工具与说明
├── docs/                      # 状态/架构/治理/研究记录（本文件所在）
├── tools/research/            # 研究用 probe 脚本（如 bk11_baostock_probe.py）
└── .github/workflows/ci.yml   # CI：后端测试 + 前端构建/单测 + Playwright E2E
```

---

## 5. 后端模块详解

> 模块文件均位于 `backend/`。以下按领域分组，每个模块给出职责与关键类/函数。

### 5.1 持仓操作建议管线（`portfolio_advice_*`，18 个文件）

这是**最核心的确定性链路**。分层：`contracts`（中立契约）→ `policy`（唯一政策源）→ 确定性校验层 → `pipeline`（编排）→ `prompt/context`（AI 输入）→ `service`（编排入口）→ `trace_adapter`（账本适配）。

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `portfolio_advice_contracts.py` | 契约唯一来源：Schema 版本、动作枚举、交易单位，无任何 IO/AI | `SCHEMA_VERSION`("portfolio-advice-v0.1")、`ACTIONS`、`ACCOUNT_ACTIONS`、`CONFIDENCE_LEVELS`、`LOT_SIZE=100` |
| `portfolio_advice_policy.py` | **投资政策唯一代码来源**：比例档位、置信度上限、现金安全垫 | `PortfolioAdvicePolicy`、`POLICY`（单例）、`ADD_TIERS`(10/20)、`REDUCE_TIERS`(10/20/30)、`CONFIDENCE_CAP`、`CASH_RESERVE_PCT`(0.10) |
| `portfolio_advice_schema.py` | AI 输出 schema 归一化与基础工具 | `validate_inputs()`、`normalize_holding_schema()`、`num_or_none()`、`round2()`、`dedupe_str_list()` |
| `portfolio_advice_pipeline.py` | **确定性管线编排**（固定七阶段状态机） | `PipelineState`、`validate_portfolio_advice()`、七阶段函数（`schema_validation → legacy_compatibility → fact_reconciliation → policy_audit → execution_calculation → narrative_audit → final_assembly`）、`resolve_generated_at()` |
| `portfolio_advice_compat.py` | v0.1 Legacy 兼容：缺失持仓合成、账户动作规范化 | `align_holdings()`、`synthesize_missing_holding()`、`normalize_account_action()` |
| `portfolio_advice_fact_reconciler.py` | 用 Context 权威事实重算持仓视图 | `reconcile_holding_facts()`、`portfolio_summary_from_context()`、`market_status_from_context()` |
| `portfolio_advice_policy_audit.py` | 执行比例与 POLICY 档位对齐，违规抛错 | `audit_execution_size()` |
| `portfolio_advice_execution.py` | 确定性执行计算：整手取整、金额估算 | `floor_to_lot()`、`compute_execution_quantity()`、`calculate_execution()` |
| `portfolio_advice_narrative_audit.py` | AI 叙述审计：未授权数字、金额表述、limitation 规范化 | `audit_holding_narrative()`、`normalize_top_level_lists()` |
| `portfolio_advice_context.py` | 构建传给 AI 的上下文（持仓/行情/证据/limitations） | `build_portfolio_advice_context()`、`render_portfolio_advice_context()` |
| `portfolio_advice_prompt.py` | 组装系统/用户提示词 | `build_portfolio_advice_messages()`、`render_policy_prompt_rules()` |
| `portfolio_advice_service.py` | **服务编排入口**：市场闸门 → 上下文 → 模型 → JSON 解析 → 管线校验 → 持久化 → 账本归档 | `generate_portfolio_advice()`、`_parse_model_json()`、错误族 `PortfolioAdviceUnavailableError / MarketDataError / ModelError / ModelOutputError / PersistError`、闸门记录 `_record_gate_blocked/_record_gate_allowed` |
| `portfolio_advice_validator.py` | 兼容 Facade（重导出 pipeline） | `validate_portfolio_advice()` |
| `portfolio_advice_errors.py` | 模型失败对外文案分类（fail closed） | `public_model_error_detail()`、`MODEL_ERR_*` 固定 502 文案 |
| `portfolio_advice_account_metrics.py` | 追加账户资金面指标（不进模型输入） | `attach_account_funding_metrics()` |
| `portfolio_advice_cash_constraint.py` | 可用现金安全垫约束 add 金额 | `apply_available_cash_constraints()` |
| `portfolio_advice_sellable.py` | T+1 同日不可卖提醒 | `apply_sellable_quantity_advisory()` |
| `portfolio_advice_trace_adapter.py` | 建议 → 决策账本确定性事实视图 | `parse_account_action()`、`iter_authoritative_holdings()`、`holding_execution_payload()` |

**错误码契约**（service → HTTP）：无持仓 409；市场核心不可用 503；模型失败/输出无效 502；参数非法 400；内部未预期 500。

### 5.2 决策与证据账本

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `evidence_thesis_store.py` | 证据-投资逻辑账本存储（`evidence_thesis.db`），WAL 感知只读快照 | `write_transaction()`、`read_transaction()`、`readonly_health_snapshot()`、`initialize_store()` |
| `evidence_thesis_service.py` | 证据/Thesis 领域服务：修订版本控制、stake 立场 | `create_evidence()`、`create_thesis()`、`link_evidence()`、`update_stance()`、`diff_revisions()` |
| `evidence_thesis_router.py` | 账本 REST API | `EvidenceCreateIn` 等模型、`RevisionConflictHTTPException`(409) |
| `decision_trace_store.py` | 决策追踪账本（`decision_trace.sqlite3`），保存整包决策运行 | `save_decision_run_bundle()`、`get_decision_run()`、`DecisionTraceCorruptedError` |
| `decision_evidence_service.py` | 建议结果归档为决策证据 bundle | `archive_decision_evidence()`、`generate_decision_run_id()` |
| `decision_evidence_router.py` | 决策证据查询（参数白名单） | `list_decision_evidence()`、`get_evidence_by_advice()` |
| `decision_feedback_store.py` | 决策反馈存储（`decision_feedback.sqlite3`） | `insert_record()`、`void_record()` |
| `decision_feedback_service.py` | 反馈业务：校验 advice_ref / trade_id 存在性 | `create_feedback()`、`void_feedback()` |
| `decision_feedback_router.py` | 反馈 API | `create_feedback/list_feedbacks/get_feedback/void_feedback` |
| `signal_ledger_store.py` | 信号账本（复用 `decision_trace.sqlite3` 的 `signal_entries` 表） | `save_signal_entry()`、`list_signal_entries()` |
| `signal_ledger_service.py` | 从建议/证据提取结构化信号入库 | 信号提取/归档函数 |
| `signal_ledger_router.py` | 信号查询 API | `list_signals` |
| `decision_cockpit_signals.py` | 驾驶舱信号纯计算（估值/趋势/情绪/现金可执行） | `evaluate_value()`、`evaluate_trend()`、`build_candidate_pool()` |
| `decision_cockpit_store.py` | 驾驶舱存储（共享 `daily_reviews.sqlite3`），明日计划乐观锁 | `upsert_evidence()`、`create_plan()`、`freeze_plan()`、`TomorrowPlanConflictError` |
| `decision_cockpit_service.py` | 明日计划编排：候选池 → 信号 → AI 解释 → 持久化/冻结 | `generate_tomorrow_plan()`、`freeze_tomorrow_plan()`、`get_overview()`、错误族 `DecisionCockpitError/MarketDataError/ModelError/SnapshotError` |
| `decision_cockpit_today.py` | 今日实时行动聚合（只读） | `get_today_actions()` |
| `decision_analytics_service.py` | 决策采纳率/结果统计（只读 SQL 聚合） | `get_adoption_summary()`、`get_outcome_summary()` |
| `decision_analytics_router.py` | 决策分析 API | `get_adoption_summary/get_outcome_summary/get_stock_summary` |

### 5.3 数据健康（`data_health_*`）

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `data_health_service.py` | 数据健康领域模型：record 结构、stale/intraday 判定、质量映射、聚合 | `DataHealthRecord`(TypedDict)、`make_record()`、`is_stale_cn_trade_date()`、`map_gate_event()`、`aggregate_health()`、`compute_overall()` |
| `data_health_event_store.py` | 健康事件日志（JSON 文件，线程安全原子写） | `record_success/record_partial/record_failure`、`record_gate_blocked()`、`safe_call()` |
| `data_health_adapters.py` | 15+ 数据源统一适配为 `DataHealthAdapter` 协议 | `DataHealthAdapter`(Protocol)、`validate_data_health_record()`、`build_adapters()`、`collect_all_records()`、`get_health_overview()` |
| `data_health_router.py` | 健康 API（总览/单源详情） | `get_data_health()`、`get_data_health_source()` |

适配器清单：DailyReview、EventSource、PortfolioQuotes、Quotes、Announcements、Financials、SectorResearch、NorthboundCapitalFlow、TopRiskAnalysis、TechnicalIndicators、Bk11History、PortfolioAdviceGate、NewsRadar、MyReports、WatchlistPortfolioStorage、EvidenceLedger。

### 5.4 交易与绩效

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `trade_ledger_store.py` | 成交账本（`trade_ledger.sqlite3`，表 `trade_records`） | `open_write_connection()`、`insert_record()`、`void_record_atomic()`、`TradeLedgerCorruptedError` |
| `trade_ledger_service.py` | 成交业务规则：advice/thesis 引用校验、部分成交、级联作废 | `create_trade_record()`、`void_trade_record()`、`resolve_db_path()`（`VIBE_RESEARCH_TRADE_LEDGER_DB`） |
| `trade_ledger_router.py` | 成交 API | 创建/查询/作废端点 |
| `performance_attribution_store.py` | 收益归因快照（`performance_attribution.sqlite3`，两张表） | `save_snapshot()`（事务）、`get_snapshot()` |
| `performance_attribution_service.py` | 收益归因计算并落库 | `compute_attribution()`、`save_attribution_snapshot()` |
| `performance_attribution_router.py` | 归因 API | `get_attribution/create_snapshot/list_snapshots` |
| `ai_result_store.py` | AI 生成结果存储（共享 `daily_reviews.sqlite3`，表 `ai_generated_results`） | `upsert_result()`、`serialize_payload()`、`AiResultPayloadCorruptedError` |
| `ai_result_service.py` | AI 结果校验与持久化编排 | `save_daily_review_ai()`、`save_portfolio_advice()`、`compute_portfolio_fingerprint()` |
| `account_event_store.py` | 账户事件账本（与 trade_ledger 同库，表 `account_events`） | `insert_event()`、`atomic_bootstrap()`、`ensure_migrated()`、错误族 `AccountEventStoreError/Corrupted/NotFound` |

### 5.5 P0 Foundation（持仓/账户事实链）

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `position_reality_service.py` | 持仓现实：bootstrap 预览/提交、纠错、级联作废、对账 | `bootstrap_preview()`、`bootstrap_commit()`、`create_correction()`、`derived_positions()`、`position_reconciliation()` |
| `position_reality_router.py` | 持仓现实 API | `bootstrap_preview/bootstrap_commit/create_correction/derived_positions/void_trade_cascade` |
| `account_reality_service.py` | 账户现实核算：现金双源、settled 定价、settled NAV | `get_account_reality()`、`_cash_reconciliation()`、`_settled_nav()` |
| `account_reality_router.py` | 账户现实 API | `account_reality()` |
| `cash_event_service.py` | 现金事件业务（5 类语义事件 + 纠错 + 有效流） | `create_cash_event()`、`correct_cash_event()`、`effective_cash_events()` |
| `cash_event_router.py` | 现金事件 API | `create_cash_event/list_cash_events/correct_cash_event` |
| `campaign_store.py` | 战役存储（`campaigns.sqlite3`）：身份/策略/生命周期/状态机约束 | `create_campaign()`、`transition_campaign()`、`bind_campaign_thesis()`、错误族 `CampaignStoreError/TransitionConflict/ThesisBindingConflict` |
| `campaign_service.py` | 战役业务：代码/策略校验、thesis 绑定（只读证据账本） | `create_campaign()`、`bind_campaign_thesis()` |
| `campaign_router.py` | 战役 API | `CampaignCreateIn` 等模型与端点 |
| `account_execution_policy.py` | 账户执行政策（JSON 文件） | `get_account_execution_policy()`、`save_account_execution_policy()` |
| `account_execution_policy_router.py` | 执行政策 API | `get_policy()`、`update_policy()` |

### 5.6 数据获取层

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `astock.py` | **A 股数据统一入口**：腾讯/东财/akshare/mootdx 多源，行情/研报/财报/K线/资金/涨停池 | `tencent_quote()`、`index_quote()`、`eastmoney_reports()`、`kline()`、`financials()`、`a_share_snapshot()`、`em_zt_topic_pool()`、`dragon_tiger_board()`、`margin_trading()`、`block_trade()`、`DependencyMissing` |
| `market.py` | 市场总览/情绪/宽度/板块排名聚合（带缓存） | `get_overview()`、`get_short_term_emotion()`、`calculate_market_breadth()`、`get_board_ranking()` |
| `gstock.py` | 全球行情（美/港/全球指数，东财 push2） | `global_indices()`、`us_hk_stock()`、`resolve_symbol()` |
| `newsradar.py` | RSS 资讯雷达（12 赛道并发抓取 + 缓存） | `fetch_radar()`、`get_radar()`、`migrate_radar_cache()` |
| `sector_research_data.py` | 行业研报发现 + 板块动态数据 | `SectorDataSource`、`discover_sector_reports()`、`get_sector_dynamic_data()` |
| `northbound_capital_flow.py` | 北向资金（沪深）日统计 + 历史 | `get_northbound_capital_flow()`、`get_northbound_history_days()`、`unavailable_envelope()` |
| `top_risk_engine.py` | 顶部风险引擎（YAML 驱动评估器） | `TopRiskEngine` |
| `top_risk_evaluators.py` | 注册式评估器 | `register(name)`、`narrative_divergence`、`crowding`、`runup_exhaustion`、`catalyst_priced_in`、`valuation_cap` |
| `top_risk_service.py` | 顶部风险编排 + trace 归档 | `analyze_top_risk()`、`attach_trace_and_archive()` |
| `top_risk_schema.py` | 顶部风险数据模型 | `TopRiskResult`、`TopRiskEnvelope`（pydantic） |
| `screener_models.py` | 选股器 pydantic 严格模型 | `ScreenerEvaluateIn`、条件模型族、`ScreenerEvaluateOut` |
| `screener_service.py` | 按条件评估股票、板块代表股 | 并发池 ≤4 |
| `screener_router.py` | 选股器 API | 评估/代表股端点 |
| `technical_indicators.py` | **纯计算**：SMA/EMA/MACD/KDJ/RSI/BOLL/量比 | `compute_indicators()` |
| `technical_indicators_router.py` | 技术指标 + 北向历史 API | 端点族 |
| `bk11_tushare_facts_adapter.py` | Tushare 全市场快照 → 标准化短线事实 | `fetch_tushare_facts_snapshot()` |
| `bk11_tushare_ingestion_service.py` | 按交易日注入 v02 事实 | `ingest_trade_date()` |
| `bk11_history_service.py` / `bk11_history_router.py` | 短线历史快照只读查询 | 历史查询端点 |
| `tushare_pro_client.py` | 无状态 Tushare Pro HTTP 客户端（Token 仅环境变量） | `TushareClient.query()`、错误族 `TushareClientError/CredentialMissing` |
| `short_term_*.py`（15 文件） | 短线事实计算族，全部确定性纯计算 | 涨停池适配、连板梯队 `compute_limit_up_ladder()`、市场事实、断层、日度事实 v01/v02、摘要/摘要文本/对比、快照择优、晋级契约校验、覆盖门 |

### 5.7 其他模块

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `app.py` | FastAPI 主应用：路由/异常/中间件/SSE | `lifespan()`（启动调度器）、`_require_api_key()`、`TTLCache`（LRU+TTL）、业务端点（chat/portfolio/advice/watchlist/复盘/分析等） |
| `portfolio.py` | 持仓 JSON 存储 + 定时刷新 | `add_holding/remove_holding/update_holding/close_position`、`get_portfolio()`、`start_scheduler()`、`PortfolioDataCorruptedError` |
| `account_profile.py` | 账户资金 JSON | `load_account_profile()`、`save_account_profile()` |
| `myreports.py` | 研报库（文件 + JSON 索引） | `save_report()`、`import_report_bytes()`、`classify()`、`build_browse()`、`ReportIndexCorruptedError` |
| `watchlist_store.py` | 自选股 JSON（ETag 乐观锁） | `get_watchlist_status()`、`save_watchlist()`、`merge_watchlist()`、`WatchlistVersionConflictError` |
| `chat.py` | **LLM 通道层**：OpenAI 兼容 HTTP + CLI、流式、工具执行、SSRF 防护 | `run_chat_stream()`、`run_chat_cli_stream()`、`_exec_tool()`、`_check_base_url()`、`prepare_daily_review_messages()` |
| `cli_runtime.py` | 本机 AI CLI 探测与调用 | `detect_cli()`、`run_cli_stream()`、`CliUnavailable` |
| `daily_review.py` | 每日复盘生成（确定性组装）+ SWR 缓存策略 | `generate_daily_review()`、`get_daily_review_for_display()`、`refresh_daily_review_for_display()`、`DailyReviewRefreshError` |
| `daily_review_context.py` | 复盘上下文投影 | `build_daily_review_ai_context()` |
| `daily_review_ai_prompt.py` | 复盘 AI 提示词 | `build_daily_review_messages()` |
| `daily_review_cache.py` | 复盘 JSON 缓存持久化 | `should_persist_review()`、`save_latest_review()` |
| `daily_review_errors.py` | 对外错误文案消毒 | `sanitize_review_public_fields()` |
| `review_store.py` | 复盘历史快照（`daily_reviews.sqlite3`，表 `daily_review_snapshots`） | `save_review_snapshot()` |
| `review_history.py` | 复盘历史库路径 + 快照读写 | `resolve_review_db_path()`（`VIBE_RESEARCH_REVIEW_DB`）、`save_current_daily_review()` |
| `review_compare.py` | 两份复盘快照结构化对比 | `compare_daily_review_snapshots()` |
| `alert_rules.py` / `alert_rule_store.py` / `alert_rule_router.py` | 价格/指标预警规则（`alert_rules.sqlite3`） | evaluator、store、API |
| `limit_up_shadow.py` | 涨停影子湖（原始响应捕获 → 规范化重放 → canonical 发布） | `RawResponseCapture`、`normalize_adapter_snapshot()`、`publish_canonical_fact()` |
| `fact_lake_store.py` | 事实湖存储引擎（控制库 + parquet 分区，哈希校验） | `FactLake` 类、`initialize_fact_lake()`、`payload_sha256()`、12 个错误类型 |
| `data_contracts.py` | 数据契约定义 | 供 shadow/fact-lake 使用 |
| `mcp_server.py` | MCP（stdin/stdout JSON-RPC）入口，复用 chat 工具 | `main()`、`_handle()` |
| `trade_calendar.py` | A 股交易日历（JSON） | 交易日换算/判定 |
| `intel_digest_service.py` / `intel_digest_store.py` / `intel_digest_router.py` | Intel 每日简报（`intel_digest.sqlite3`） | URL 规范化、指纹去重、material status 推导 |

---

## 6. 数据存储

### 6.1 SQLite 数据库

| 数据库文件 | Store 模块 | 主要表 | 路径优先级（环境变量） |
|---|---|---|---|
| `trade_ledger.sqlite3` | `trade_ledger_store` / `account_event_store` | `trade_records`、`account_events` | `VIBE_RESEARCH_TRADE_LEDGER_DB` → `VR_DATA_DIR` → `~/.vibe-research` |
| `daily_reviews.sqlite3` | `review_store` / `ai_result_store` / `decision_cockpit_store` | `daily_review_snapshots`、`ai_generated_results`、`decision_evidence`、`decision_signals`、`tomorrow_plans` | `VIBE_RESEARCH_REVIEW_DB` |
| `decision_trace.sqlite3` | `decision_trace_store` / `signal_ledger_store` | `decision_runs`、`evidence_items`、`explanation_items`、`signal_entries`、`decision_outcomes` | `VR_DATA_DIR` → `~/.vibe-research` |
| `evidence_thesis.db` | `evidence_thesis_store` | `evidence_records`、`investment_theses`、`thesis_revisions`、`thesis_evidence_links`（含 WAL/备份） | `VIBE_RESEARCH_EVIDENCE_THESIS_DB` → `VR_DATA_DIR` |
| `decision_feedback.sqlite3` | `decision_feedback_store` | `decision_feedback` | `VR_DATA_DIR` |
| `performance_attribution.sqlite3` | `performance_attribution_store` | `attribution_snapshots`、`attribution_positions` | `VR_DATA_DIR` |
| `campaigns.sqlite3` | `campaign_store` | `campaigns`、`campaign_transitions`、`campaign_thesis_bindings`、`schema_meta` | `VR_DATA_DIR` |
| `alert_rules.sqlite3` | `alert_rule_store` | `schema_meta`、`alert_rules` | `VR_DATA_DIR` |
| `short_term_facts.sqlite3` | `short_term_fact_store` | `schema_meta`、`fact_snapshots` | `VR_DATA_DIR` |
| `intel_digest.sqlite3` | `intel_digest_store` | `intel_daily_digests` | `VR_DATA_DIR` |
| `fact_lake_control.sqlite3` | `fact_lake_store` | `schema_meta`、`observations`、`reconciliation_results`、`normalized_observations`、`canonical_publications`；原始/规范化数据为 parquet | fact lake 根目录 |

### 6.2 JSON / 文件存储（非 SQLite）

| 文件 | 模块 | 内容 |
|---|---|---|
| `portfolio.json` | `portfolio.py` | holdings + closed + last_refresh（含 legacy 迁移） |
| `account_profile.json` | `account_profile.py` | total_assets / available_cash |
| `watchlist.json` | `watchlist_store.py` | 后端权威自选股（SCHEMA_VERSION="watchlist.v1" + ETag） |
| 研报文件 + 索引 | `myreports.py` | 用户上传研报，默认用户目录，`VR_REPORTS_DIR` 可指定 |
| 复盘缓存 JSON | `daily_review_cache.py` | 磁盘 latest 复盘包 |
| 健康事件日志 JSON | `data_health_event_store.py` | success/partial/failure/gate 事件流 |
| 资讯雷达缓存 | `newsradar.py` | RSS 抓取缓存 |
| 执行政策 JSON | `account_execution_policy.py` | 账户执行政策 |
| 交易日历 | `trade_calendar.py` | `backend/data/cn_a_share_trade_calendar_v01.json` |

> **数据边界**：持仓、账户、交易、私密笔记、模型密钥**不进 Git**；真实用户数据存放在用户目录 / `VR_DATA_DIR`；部分前端配置与模型密钥在浏览器 `localStorage`。

---

## 7. 前端模块详解

### 7.1 页面（`frontend/src/pages/`，30 个）

| 页面 | 职责 |
|---|---|
| `DailyReview.tsx` | 每日复盘（市场环境 + 板块 + 个股，SWR 展示） |
| `Portfolio.tsx` | 持仓管理 + 操作建议（advice） |
| `StockData.tsx` | 个股数据（行情/研报/资金面/筹码） |
| `DecisionCockpit.tsx` | 明日决策驱动舱 |
| `DecisionEvidence.tsx` / `EvidenceList/New/Detail.tsx` | 决策证据 / 证据（Evidence）CRUD |
| `ThesisList/New/Detail/Revision.tsx` | 投资逻辑（Thesis）与修订 |
| `Trades.tsx` | 成交账本 |
| `DecisionFeedback.tsx` | 决策反馈 |
| `DecisionPerformance.tsx` | 决策绩效 |
| `PerformanceAttribution.tsx` | 收益归因 |
| `SignalLedger.tsx` | 信号账本 |
| `Screener.tsx` | 选股器 |
| `Sectors.tsx` / `SectorDetail.tsx` / `SectorResearchPage.tsx` | 板块列表 / 板块详情 / 板块研究工作台 |
| `MarketHistory.tsx` | 短线市场历史（BK-11） |
| `Intel.tsx` | Intel 简报 |
| `DataHealth.tsx` | 数据健康中心 |
| `MyReports.tsx` | 个人研报库 |
| `Notes.tsx` | 笔记 |
| `Watchlist.tsx` | 自选股 |
| `AccountPolicy.tsx` | 账户执行政策 |
| `Settings.tsx` | 设置（AI 接入等） |

### 7.2 核心 lib（`frontend/src/lib/`）

| 文件 | 职责 |
|---|---|
| `api.ts` | 后端 HTTP 客户端统一封装（`/api/*`，含降级） |
| `llm.ts` / `ai-models.ts` | AI 模型配置读取（localStorage）与调用协议 |
| `watchlist.ts` | 自选股本地缓存 + 后端同步 |
| `dailyReviewAiTaskStore.ts` 等（`stores/`） | zustand 状态：AI 任务/建议请求协调 |
| `intelDigestOrchestrator.ts` | Intel 简报生成状态机 |
| `decisionCockpit.ts`、`tradeLedgerView.ts` 等 | 各页面视图模型与格式化 |
| `klineIndicatorOverlay.ts` | K 线指标叠加（KDJ 等） |
| `technicalIndicatorsView.ts` | 技术指标展示 |

### 7.3 板块研究数据（`frontend/src/data/sectorResearch/`）

按行业分组（ai-computing / cpo / hbm / pcb / semiconductor / smart-driving / solid-state-battery / defense / fusion / humanoid / low-altitude / energy-storage 等约 20 个行业），每个行业含 `overview.ts`（总览）、`industry.ts`（产业图谱）、`sources.ts`（来源）、`pricing.ts` / `value.ts`（定价/价值）等静态研究数据，`invariants.ts` 保证数据不变式。

---

## 8. 依赖关系

### 8.1 模块依赖方向（确定性优先）

```
前端 pages → lib/api.ts → backend /api/*

backend：
  app.py → 全部 router / service / store（装配根）
  router → service → store（SQLite/JSON）
  service → 确定性层 + AI 通道
  portfolio_advice_service → daily_review → market → astock
                         → chat/cli_runtime（模型）
                         → portfolio_advice_pipeline（七阶段）
                         → decision_evidence_service / signal_ledger_service（归档）
  evidence_thesis_service → evidence_thesis_store（只读供 campaign 使用）
  decision_cockpit_service → decision_cockpit_signals（纯计算）+ decision_cockpit_store
  account_reality_service → account_event_store + cash_event_service + position_reality_service + trade_ledger_*
  limit_up_shadow → short_term_limit_up_pool_adapter + fact_lake_store + data_contracts（影子能力，不接入生产）
```

### 8.2 关键规则

- **投资政策唯一来源**：`portfolio_advice_policy.POLICY`；`portfolio_advice_contracts` 只承载 Schema/枚举/交易单位。
- **校验唯一执行点**：`portfolio_advice_pipeline.validate_portfolio_advice()`（validator 是 Facade）。
- **复盘展示 vs 业务**：展示路径可用 stale 磁盘包（SWR）；持仓建议/复盘 AI 只用 fresh `generate_daily_review()`。
- **账户资金不进入 AI**：只做执行阶段安全垫约束（`portfolio_advice_cash_constraint`）。
- **存储同库共享**：`trade_ledger.sqlite3`（成交 + 账户事件，保证事务性）、`daily_reviews.sqlite3`（复盘历史 + AI 结果 + 驾驶舱）、`decision_trace.sqlite3`（决策追踪 + 信号）。
- **外部数据失败降级**：市场层统一 `normal/partial/unavailable` 信封（HTTP 200），仅逃逸异常 502；`data_health_event_store` 记录每次调用的健康事件。

---

## 9. 项目运行方式

### 9.1 Linux（Ubuntu / CPython 3.11）

```bash
git clone https://github.com/guilaile95/Vibe-Research.git
cd Vibe-Research/backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py311.lock.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

### 9.2 Windows PowerShell（CPython 3.12.10）

```powershell
git clone https://github.com/guilaile95/Vibe-Research.git
Set-Location Vibe-Research\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-windows-py312.lock.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900
```

### 9.3 前端

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5899（/api 代理到 127.0.0.1:8900）
```

### 9.4 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `VR_DATA_DIR` | 用户数据目录（持仓/自选/数据库等） | `~/.vibe-research` |
| `VR_REPORTS_DIR` | 个人研报目录 | 用户目录 |
| `VR_API_KEY` | 启用后所有 `/api/*`（除 health）要求 `Authorization: Bearer <key>` | 空（开放） |
| `VR_ALLOW_ORIGINS` | CORS 白名单（逗号分隔） | `*` |
| `VIBE_RESEARCH_REVIEW_DB` | 复盘库路径 | 平台用户数据目录 |
| `VIBE_RESEARCH_TRADE_LEDGER_DB` | 成交账本库路径 | `VR_DATA_DIR` |
| `VIBE_RESEARCH_EVIDENCE_THESIS_DB` | 证据账本库路径 | `VR_DATA_DIR` |
| `VITE_API_URL` | 前端代理目标 | `http://127.0.0.1:8900` |
| `TUSHARE_TOKEN` | Tushare Token（BK-11 注入；live 可用性未证明） | 无 |
| `HITHINK_FINANCE_API_KEY` | HiThink 数据（仅本机环境变量，禁止进 Git） | 无 |

### 9.5 AI 接入（可选）

- API 接入：前端 Settings 配置 `baseURL / apiKey / model`（OpenAI 兼容），随请求传入，后端不持久化 key。
- 订阅接入：`provider=cli-*` 时后端调本机已登录 CLI（`cli_runtime.detect_cli`）。
- MCP：`claude mcp add vibe-research -- <path>/backend/.venv/bin/python <path>/backend/mcp_server.py`，暴露 `query_quote / query_valuation / query_reports / query_news` 四个工具。

---

## 10. 测试与 CI

### 10.1 后端测试

```bash
cd backend
# 全量离线测试（不跑 live 标记用例）
.venv/bin/python -m pytest -q tests -m "not live"
# 单文件聚焦
.venv/bin/python -m pytest -q tests/test_short_term_limit_up_ladder.py
# 语法检查
.venv/bin/python -m py_compile tests/test_xxx.py
```

测试分类（AGENTS.md 要求）：LOCAL / EXACT_HEAD_CI / BROWSER_RUNTIME / LIVE_EXTERNAL_DATA 必须明确区分，未运行要写 `NOT_RUN`。fixtures 使用 tmp/fake 数据，禁止写真实用户文件。

### 10.2 前端测试

```bash
cd frontend
npm test                    # Node 单测（node --experimental-strip-types）
npm run test:e2e:smoke      # Playwright smoke
npm run test:e2e:thesis     # 证据-Thesis 真实 E2E
npm run test:e2e:data-health
npm run test:e2e:intel-digest
```

### 10.3 CI（`.github/workflows/ci.yml`）

| Job | 内容 |
|---|---|
| `backend` | Python 3.11 + Linux 锁文件安装、锁文件可复现校验（piptools）、`pytest -m "not live"` |
| `frontend` | Node 22 + `npm ci` + `npm run build` + `npm test` |
| `e2e-smoke` | Playwright Chromium + stock-data smoke + top-risk E2E |
| `e2e-thesis-smoke` / `e2e-data-health-smoke` / `e2e-intel-digest-smoke` | 各真实 E2E（起后端 + 前端） |
| `windows-lock-check` | Windows 3.12.10 锁文件校验 + 离线测试 |
| `whitespace` | 变更行 whitespace 检查 |

---

## 11. 关键设计约束（工程纪律摘要）

1. **Fail Closed**：高价值事实（账本损坏、持仓矛盾、迁移非法、stale 决策、unknown eligibility）必须 fail closed；`UNKNOWN` 保持 `UNKNOWN`。
2. **数据安全**：真实持仓/账户/交易/凭证/私密笔记不得进 Git；API Key 不进源码/日志/测试快照/localStorage 存储；未知错误码返回固定 HTTP 500 文案，不透 traceback。
3. **存储只读快照**：`evidence_thesis_store` 健康查询必须走 WAL 感知只读快照、锁内完成、不建 sidecar、不写库；无法安全读则返回 `SOURCE_UNAVAILABLE`。
4. **兼容性**：内部废弃实现无消费者可删；保护用户真实数据、Trade Ledger、Evidence/Thesis 历史、Frozen Decision、已有本地 DB、正式 UI 稳定契约。
5. **Git 纪律**：禁止 `git branch -D` / `clean` / `reset` / destructive `restore` / force push / 对已 push 提交 amend/rebase；修正用新 commit；不得直接改 push stable。
6. **确定性/AI 边界**：AI 不得绕过 Hard Risk、修改事实、把 UNKNOWN 变事实、自动改 Original Thesis、自动建 Formal Decision、自动交易。

---

## 12. 附录：常用 API 端点速查

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 健康检查 |
| `GET /api/daily-review` / `POST /api/daily-review/refresh` / `POST /api/daily-review/analyze` | 每日复盘展示 / 刷新 / AI 流式分析 |
| `POST /api/daily-review/history/save`、`GET /api/daily-review/history*` | 复盘历史保存与查询/对比 |
| `GET /api/portfolio`、`POST/PUT/DELETE /api/portfolio/holding`、`POST /api/portfolio/close` | 持仓 CRUD |
| `POST /api/portfolio/advice` | **持仓操作建议**（核心 AI 链路） |
| `GET/PUT /api/account-profile` | 账户资金 |
| `GET /api/account/reality`、`/api/cash-events*`、`/api/position-reality*` | P0 Foundation 事实链 |
| `/api/campaigns*` | 战役（Campaign） |
| `/api/evidence*`、`/api/theses*` | 证据与投资逻辑账本 |
| `/api/decision-feedback*`、`/api/decision-evidence*`、`/api/signal-ledger*`、`/api/decision-analytics*` | 决策反馈/证据/信号/分析 |
| `/api/trade-ledger*`、`/api/performance-attribution*` | 成交账本与收益归因 |
| `/api/decision-cockpit/*` | 明日计划驾驶舱 |
| `/api/data-health*` | 数据健康中心 |
| `/api/intel-digests*` | Intel 简报 |
| `/api/watchlist`、`/api/myreports*`、`/api/account-execution-policy` | 自选/研报/执行政策 |
| `/api/quote`、`/api/indices`、`/api/kline`、`/api/financials`、`/api/valuation*`、`/api/reports`、`/api/news`、`/api/announcements`、`/api/margin`、`/api/block-trade`、`/api/holders`、`/api/dividend`、`/api/fund-flow`、`/api/dragon-tiger`、`/api/lockup`、`/api/blocks`、`/api/hot-concepts`、`/api/investor-qa` | 个股数据族 |
| `/api/market/overview`、`/api/market/emotion`、`/api/market/breadth`、`/api/market/boards`、`/api/market/northbound`、`/api/market/top-risk` | 市场聚合 |
| `/api/global/indices`、`/api/global/stock` | 全球市场 |
| `/api/sector-research/*`、`/api/technical-indicators/*`、`/api/screener/*`、`/api/bk11-history/*`、`/api/alert-rules*` | 板块研究/技术指标/选股/短线历史/预警 |
| `POST /api/chat` | 系统 AI 对话（流式 NDJSON） |

---

## 13. 维护说明

- 本文件是**工程代码地图**（描述"代码现在是什么"），不是授权文档。当前执行授权以 [`docs/NEXT_TASK.md`](NEXT_TASK.md) 为准，产品方向以 [`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md) 为准。
- 模块发生结构性变化（新增数据库、管线阶段、路由族）时，应同步更新本文件 §5/§6/§8/§12。
- 短生命周期信息（worktree、瞬时 CI、本地未提交状态）不在本文件维护。
