# Vibe-Research Code Wiki v2

> 本文档是仓库的 **Engineering Navigation Index / Anti-Rewheel Index**：回答“代码在哪里、现有 subsystem 做什么、哪个模块拥有 authority、数据存在哪里、开发前应先复用什么”。
>
> - **Snapshot Branch**：`feature/research-system-v01`
> - **Snapshot Head**：`60945d15c7574839eb17600a1417e990cd395f6a`
> - **Snapshot Date**：2026-08-12
> - 项目总体状态：[`PROJECT_STATE.md`](PROJECT_STATE.md)
> - 产品方向：[`PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)
> - 执行授权：[`NEXT_TASK.md`](NEXT_TASK.md)
> - 调用链细节：[`ARCHITECTURE.md`](ARCHITECTURE.md)
> - 新会话与 Validation V2 执行协议：[`CONVERSATION_HANDOFF.md`](CONVERSATION_HANDOFF.md)
> - 统计数字（文件数/页面数）仅是该 Snapshot 的导航信息，不是长期不变量。
>
> **重要：本 Wiki 不是产品、语义或实施 Authority。** 任何开发决策必须回到 exact-head source/tests 验证。若本文与 North Star、NEXT_TASK、PROJECT_STATE 或 exact-head code/tests 冲突，本文让位。

---

## 0. 文档权威、Authority Map 与 Anti-Rewheel

### 0.1 文档冲突优先级

开发时按以下顺序解释项目：

1. **`PRODUCT_NORTH_STAR_V01.md`**：产品长期方向、决策语义与产品宪法。
2. **`NEXT_TASK.md`**：当前明确授权的实现工作；North Star 本身不等于实施授权。
3. **exact-head source + tests**：代码现在实际上做什么的最终工程事实。
4. **`PROJECT_STATE.md`**：项目阶段、已完成/未完成状态与治理同步。
5. **`CODE_WIKI.md`**：导航、定位、复用入口与影响分析索引。
6. README / 历史研究记录：onboarding 或背景材料。

`AGENTS.md` 属于正交的**工程执行纪律**：凡与当前工作适用时始终必须遵守，但它不替代 North Star / NEXT_TASK / source 的产品与语义 authority。

```text
Wiki hit != verified implementation fact

CODE_WIKI
  ↓ locate
exact-head source/tests
  ↓ verify
REUSE / WRAP / ADAPT / REJECT_LEGACY / NEW_REQUIRED
  ↓
implementation
```

### 0.2 Stable Authority Map（Snapshot Head）

下表只描述本 Snapshot stable 中已经成立的 authority；Draft PR 不因为存在就视为 stable 能力。

| Capability | Stable semantic authority / source | I/O / persistence | Stable status | Hard boundary |
|---|---|---|---|---|
| Campaign identity / lifecycle | `campaign_service.py` + `campaign_store.py` | `campaigns.sqlite3` | **IMPLEMENTED** | Decision Unit 不得退化为 security-only |
| Current Thesis semantics | `formal_thesis_projection_core.py` | `formal_thesis_projection.py` + Evidence/Thesis ledger | **IMPLEMENTED** | Core 是唯一 pure-domain Current Thesis authority；不得建立第二套状态机 |
| Formal / Frozen Decision | `frozen_decision_service.py` + `frozen_decision_store.py` | append-only Frozen Decision persistence | **IMPLEMENTED** | 历史 Frozen Decision ≠ current recommendation |
| Position Reality | `position_reality_service.py` | trade/account event stores | **IMPLEMENTED** | 真实持仓从事件/成交事实推导，不从 advice 反推 |
| Account Reality | `account_reality_service.py` | account / cash / position facts | **IMPLEMENTED** | settled/official 与 best-effort intraday 语义分离 |
| Data Health（source/module health） | `data_health_service.py` + adapters/event store | JSON health event log | **IMPLEMENTED** | Data Health ≠ Campaign Critical Data Usability |
| Fact Lake storage / publication | `fact_lake_store.py` + accepted Fact Lake semantic cores | SQLite control + Parquet | **IMPLEMENTED FOUNDATION** | publication/local latest ≠ PIT/provider revision |
| Contextual / legacy Top Risk | `top_risk_*` | service/trace | **IMPLEMENTED LEGACY/CONTEXTUAL** | **不是 North Star Hard Risk Gate authority**；`risk_score != hard_risk_state` |
| Portfolio Advice subsystem | `portfolio_advice_*` | advice/result/trace stores | **IMPLEMENTED EXISTING SUBSYSTEM** | **不是 Formal Decision / Decision Inbox 的替代 authority** |
| Decision Cockpit | `decision_cockpit_*` | `daily_reviews.sqlite3` | **IMPLEMENTED EXISTING SUBSYSTEM** | **不是 P0 Decision Inbox authority** |
| North Star Hard Risk Gate | — | — | **MISSING IN STABLE** | 不得从 `top_risk_*` / score 直接提升 |
| Material Change authority | — | — | **MISSING IN STABLE** | 不得把 Thesis Delta / 新 evidence 简单重命名成 Material Change |
| Campaign-specific Critical Data authority | — | — | **MISSING IN STABLE** | 全局 Data Health 不能替代 Campaign dependency evaluation |
| P0 Decision Inbox projection/runtime | — | — | **NOT IN STABLE SNAPSHOT** | Draft/未来能力在合入前不得写成 stable authority |
| Decision Assurance Coverage | — | — | **NOT IN STABLE SNAPSHOT** | Coverage ≠ Safety |

### 0.3 Anti-Rewheel Registry

开发新能力前，优先查本表，再打开 exact-head 实现验证。

| 需求 | 先复用/检查 | 禁止的重复实现或错误替代 |
|---|---|---|
| Current Thesis | `formal_thesis_projection_core` / adapter | 第二套 Thesis state machine；从 UI/cockpit 推导 Current Thesis |
| Formal Decision | `frozen_decision_*` | 新建 mutable “current decision” store；把历史 `next_best_action` 当当前建议 |
| Campaign | `campaign_*` | 按 `security_code` 合并多 Campaign；伪造 campaign_id |
| Position / holding truth | `position_reality_*` / trade ledger | 从 portfolio advice 或显示层反推真实仓位 |
| Account truth | `account_reality_*` / cash events | 在新模块重复计算一套账户余额/NAV authority |
| Data health | `data_health_*` | 把 source health 当作 Campaign Critical Data usability |
| Hard Risk | North Star contract + Current Thesis / data evidence | 直接用 `top_risk_*`、`risk_score`、单指标或 heuristic 当 Hard Risk CONFIRMED |
| Decision Inbox | Campaign + Current Thesis + Frozen Decision 等 authority | 复用 `decision_cockpit_*` / `portfolio_advice_*` heuristic 作为 Inbox 语义权威 |
| Fact Lake | `fact_lake_store` / data contracts / accepted health/projection cores | 新建第二套 lake/control DB；把 retrieval/local vintage 当 PIT/revision |
| Historical market runtime | 现有行情 / Fact Lake 能力 + Research Data Plane 设计 | 因本地数据库“有值”就自动升级为 Canonical Fact |
| Outcome / attribution | `performance_attribution_*`、Formal Decision Outcome 相关 authority | 用 feedback 替代 performance evidence；原位修改 Frozen Decision |

### 0.4 固定开发 Preflight

所有新的 production slice 在写代码前应完成：

```text
ANTI-REWHEEL PREFLIGHT

1. Read relevant CODE_WIKI sections.
2. Resolve exact stable HEAD.
3. Verify Wiki claims against exact-head source/tests.
4. Search existing authority/service/store/tests.
5. Classify each relevant capability:
   REUSE_AS_IS
   WRAP
   ADAPT
   REJECT_LEGACY
   NEW_REQUIRED
6. State what NEW decision information / assurance the new module adds.
7. Only then implement.
```

如果新模块只是重新命名现有 authority、复制已有状态或增加没有新决策信息的 wrapper，应优先拒绝或缩减。

### 0.5 Validation execution authority

本 Wiki **不复制 Validation 规则**。项目级执行协议唯一来源：

```text
docs/CONVERSATION_HANDOFF.md §4.2 VALIDATION_V2
```

任何 G/T/Z production implementation / correction 工作单默认使用该协议。关键冻结：

```text
TARGETED-FIRST
FULL_SUITE_DEFAULT_BUDGET = 1
EXACT_HEAD_CI = AUTOMATED VALIDATION GATE
CI PASS != INDEPENDENT_REVIEW_APPROVED
```

---

## 1. 项目概览

**产品定位**：Single-user Personal Local Investment OS —— 个人、本地的 A 股投资研究与决策辅助系统（非自动交易、非荐股）。

**核心使命**：围绕真实持仓与拟交易标的，减少买入、持有、卖出中的错误决策风险，同时改善长期收益。

仓库现有大体信息流：

```text
市场与数据（astock / market / gstock / 北向 / 资金面 / 资讯）
    ↓
研究、Thesis 与 Evidence（evidence_thesis_* / sector_research / myreports）
    ↓
信号和历史决策记录（decision_cockpit / signal_ledger / decision_evidence）
    ↓
持仓、账户与执行约束（position/account reality / campaign / portfolio / execution policy）
    ↓
交易、结果、反馈与收益归因（trade_ledger / decision_feedback / performance_attribution）
```

当前 stable 中已经成立的 Formal P0 Foundation 主链：

```text
Position Reality
  ↓
Campaign identity / lifecycle
  ↓
Current Thesis Projection
  ↓
Frozen Formal Decision
  ↓
Decision ↔ Trade attribution / Outcome
```

`Decision Inbox / North Star Hard Risk / Material Change / Campaign Critical Data` 在本 Snapshot 仍不能写成 stable 已实现 authority；参见 §0.2。

**工程原则**：deterministic-first。确定性层负责事实、校验、账本、状态与硬边界；AI 层负责推理、解释、挑战与 proposal，不得修改 Canonical Fact、Original Thesis 或 Frozen Decision，也不得自动交易。

---

## 2. 技术栈与依赖

### 2.1 分层技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React + TypeScript + Vite + Tailwind | React 19、Vite 6、Tailwind 3.4、ECharts 6、zustand、react-router-dom 7 |
| 后端 | FastAPI + Uvicorn | Python 3.11（Linux）/ 3.12（Windows） |
| 结构化存储 | SQLite 多库 + JSON | `sqlite3` 标准库直连，无 ORM |
| 数据湖 | DuckDB + Parquet | `fact_lake_store` / shadow canonicalization foundation |
| 可选数据依赖 | akshare / mootdx / pandas | 缺失时对应能力降级，不应破坏核心 |
| 数据获取 | requests + 多公开数据源 | 东财/腾讯/百度/巨潮/RSS 等 |

### 2.2 后端依赖入口

`backend/requirements.txt` 记录顶层依赖；平台 lock 文件才是可复现安装 authority：

- `requirements-linux-py311.lock.txt`
- `requirements-dev-linux-py311.lock.txt`
- `requirements-dev-windows-py312.lock.txt`
- `requirements-tooling.txt`（piptools 工具链）

### 2.3 前端依赖

运行时主要包括 `react`、`echarts`、`lucide-react`、`react-markdown`、`remark-gfm`、`react-router-dom`、`sonner`、`zustand`；开发依赖包括 TypeScript、Vite、Tailwind、Playwright。

---

## 3. 整体架构

### 3.1 进程与端口

```text
Browser / React SPA :5899
        │ /api/* via Vite proxy
        ▼
FastAPI / Uvicorn :8900
        │
        ├─ Router / Service / Domain / Store
        ├─ 外部公开数据源
        ├─ SQLite / JSON / Parquet
        └─ AI 通道（OpenAI-compatible 或本机 CLI）
```

`backend/app.py` 是装配根：内联核心端点、挂载 router、异常处理、可选 `VR_API_KEY` 中间件与 lifespan。

### 3.2 分层设计

| 层 | 代表模块 | 职责 |
|---|---|---|
| API / Router | `app.py`、`*_router.py` | HTTP 契约、参数校验、错误映射 |
| Service | `*_service.py` | 业务编排、跨模块调用、AI 调用 |
| Domain / Pure Core | `*_core.py`、policy、projection、indicator 等 | 纯计算、语义状态、确定性规则 |
| Store | `*_store.py` | SQLite / JSON 持久化、事务、锁、fail-closed |
| AI | `chat.py`、`cli_runtime.py`、`mcp_server.py` | 模型调用与工具通道 |
| Data Fetch | `astock.py`、`market.py`、`gstock.py`、`newsradar.py` 等 | 上游抓取、缓存、限流、降级 |

### 3.3 确定性 / AI 边界

```text
确定性层                         AI 层
facts / validation              reasoning
freshness / identity            explanation
mechanics / validated gates     challenge
state transitions               synthesis
formal immutable ledgers        proposal
```

模型输出的事实、数量、金额、建议都不能因为“由 AI 生成”而获得 authority；必须经过对应 deterministic contract。

---

## 4. 目录结构

```text
Vibe-Research/
├── AGENTS.md
├── backend/
│   ├── app.py
│   ├── *.py
│   ├── tests/
│   ├── requirements*.txt
│   └── data/
├── frontend/
│   ├── src/pages/
│   ├── src/components/
│   ├── src/lib/
│   ├── src/stores/
│   ├── src/data/sectorResearch/
│   └── tests/
├── a-stock-data/
├── global-stock-data/
├── docs/
├── tools/research/
└── .github/workflows/ci.yml
```

---

## 5. 后端 Capability Map

> 本节用于“去哪里找”；真正改代码前必须打开 exact-head 文件和测试。

### 5.1 Formal P0 Foundation

| 模块 | 职责 |
|---|---|
| `position_reality_service.py` / router | bootstrap、纠错、derived positions、reconciliation |
| `account_reality_service.py` / router | 现金双源、settled pricing、settled NAV |
| `cash_event_service.py` / router | 现金事件、纠错、effective event flow |
| `campaign_store.py` / `campaign_service.py` / router | Campaign identity、strategy、lifecycle、thesis binding |
| `formal_thesis_projection_core.py` | **Current Thesis sole pure-domain semantic authority** |
| `formal_thesis_projection.py` | Current Thesis I/O / persistence validation adapter |
| `frozen_decision_service.py` / store | Formal Decision canonical snapshot、hash、append-only freeze/read |

### 5.2 Evidence / Thesis / Decision history

| 模块 | 职责 |
|---|---|
| `evidence_thesis_store.py` / service / router | Evidence + Formal Thesis ledger、revision、binding |
| `decision_trace_store.py` | 决策运行 bundle / trace |
| `decision_evidence_service.py` / router | 决策证据归档与查询 |
| `decision_feedback_store.py` / service / router | 用户反馈及引用校验 |
| `signal_ledger_store.py` / service / router | 结构化信号账本 |
| `decision_analytics_service.py` / router | adoption / outcome 等只读统计 |

### 5.3 Portfolio Advice（existing subsystem）

这是仓库中已实现且规模较大的 Advice 子系统，但**不是当前 North Star Formal Decision / Decision Inbox 的替代 authority**。

内部结构：

```text
contracts
→ policy
→ schema / compatibility
→ fact reconciliation
→ policy audit
→ execution calculation
→ narrative audit
→ pipeline
→ service / persistence / trace
```

关键模块：

- `portfolio_advice_contracts.py`
- `portfolio_advice_policy.py`
- `portfolio_advice_pipeline.py`
- `portfolio_advice_fact_reconciler.py`
- `portfolio_advice_execution.py`
- `portfolio_advice_narrative_audit.py`
- `portfolio_advice_context.py`
- `portfolio_advice_prompt.py`
- `portfolio_advice_service.py`
- `portfolio_advice_trace_adapter.py`

**Portfolio Advice 子系统内部的投资政策唯一来源**是 `portfolio_advice_policy.POLICY`；这不把该 subsystem 提升成项目级 Formal Decision authority。

### 5.4 Decision Cockpit（existing subsystem）

| 模块 | 职责 |
|---|---|
| `decision_cockpit_signals.py` | 估值/趋势/情绪/现金可执行等纯计算 |
| `decision_cockpit_store.py` | 明日计划/证据等 persistence |
| `decision_cockpit_service.py` | 候选池、信号、AI 解释、持久化 |
| `decision_cockpit_today.py` | 今日行动聚合 |

**Hard boundary**：Cockpit 不得作为 P0 Decision Inbox semantic authority。

### 5.5 Data Health

| 模块 | 职责 |
|---|---|
| `data_health_service.py` | source/module health domain model、stale/quality/aggregate |
| `data_health_event_store.py` | success / partial / failure / gate event log |
| `data_health_adapters.py` | 多数据源统一 adapter |
| `data_health_router.py` | health overview/detail API |

**Hard boundary**：Data Health 回答 source/module 当前健康程度；它不自动回答“某 Campaign 的关键决策依赖是否充分可用”。

### 5.6 Trade / Outcome / Attribution

| 模块 | 职责 |
|---|---|
| `trade_ledger_store.py` / service / router | 实际成交账本、作废、引用校验 |
| `account_event_store.py` | 账户事件 ledger / bootstrap |
| `performance_attribution_store.py` / service / router | 收益归因快照 |
| `ai_result_store.py` / service | AI 结果校验与存储 |

Outcome 相关实现必须保持：Feedback ≠ performance evidence；Frozen Decision 不原位回填未来结果。

### 5.7 Market / Data Fetch

| 模块 | 职责 |
|---|---|
| `astock.py` | A 股数据统一入口，多公开源行情/财务/K线/资金/涨停等 |
| `market.py` | 市场总览、情绪、breadth、板块聚合 |
| `gstock.py` | 全球指数 / 美港行情 |
| `newsradar.py` | RSS 资讯雷达 |
| `sector_research_data.py` | 行业研报与动态数据 |
| `northbound_capital_flow.py` | 北向日统计与历史 |
| `technical_indicators.py` | SMA/EMA/MACD/KDJ/RSI/BOLL 等 pure compute |
| `screener_service.py` / router/models | 条件筛选 |
| `short_term_*.py` | 短线事实与 deterministic summaries |
| `tushare_pro_client.py` | Tushare Pro HTTP client |
| `bk11_tushare_facts_adapter.py` / ingestion / history | BK-11 事实注入与历史 |

### 5.8 Top Risk（legacy/contextual）

| 模块 | 职责 |
|---|---|
| `top_risk_engine.py` | YAML 驱动 existing/contextual risk engine |
| `top_risk_evaluators.py` | evaluator registry |
| `top_risk_service.py` | 编排 + trace |
| `top_risk_schema.py` | result envelope |

**Authority note**：`top_risk_*` 不是 North Star `Hard Risk Gate` 的 semantic authority；不得用 `risk_score`、单个 evaluator 或 heuristic 直接产生 `hard_risk_state=CONFIRMED`。

### 5.9 Fact Lake / Shadow Data Governance

| 模块 | 职责 |
|---|---|
| `fact_lake_store.py` | control DB + Parquet publication、hash verification |
| `data_contracts.py` | Dataset / observation contracts |
| `limit_up_shadow.py` | raw capture → normalization → canonical shadow publication |

Fact Lake 相关语义必须继续遵守：

```text
Provider Response != Canonical Fact
by_date != PIT
retrieval time != market fact time
local vintage != provider revision
```

### 5.10 AI / Misc

- `chat.py`：OpenAI-compatible HTTP / CLI streaming、tool execution、SSRF 防护。
- `cli_runtime.py`：本机 AI CLI 探测与调用。
- `mcp_server.py`：stdin/stdout JSON-RPC MCP 入口。
- `daily_review_*`：每日复盘、上下文、prompt、cache、errors。
- `myreports.py`：研报文件与索引。
- `watchlist_store.py`：自选股 JSON + ETag。
- `alert_rule_*`：价格/指标预警。
- `intel_digest_*`：Intel 每日简报。

---

## 6. Persistence Registry

### 6.1 SQLite

| 数据库 | 主要 authority / store | 主要内容 |
|---|---|---|
| `trade_ledger.sqlite3` | `trade_ledger_store` / `account_event_store` | trades、account events |
| `daily_reviews.sqlite3` | review / AI result / decision cockpit stores | daily review、AI results、cockpit/plan 等 |
| `decision_trace.sqlite3` | decision trace / signal ledger | decision runs、evidence、signals、outcomes |
| `evidence_thesis.db` | `evidence_thesis_store` | evidence、thesis、revisions、bindings |
| `decision_feedback.sqlite3` | feedback store | decision feedback |
| `performance_attribution.sqlite3` | attribution store | attribution snapshots / positions |
| `campaigns.sqlite3` | `campaign_store` | campaigns、transitions、thesis bindings |
| `alert_rules.sqlite3` | alert store | alert rules |
| `short_term_facts.sqlite3` | short-term store | fact snapshots |
| `intel_digest.sqlite3` | intel store | daily digests |
| `fact_lake_control.sqlite3` | `fact_lake_store` | observations、normalization、publication、reconciliation metadata |

**Anti-rewheel rule**：新增 persistence 前必须先查本表和现有 store。不要因为“新 feature 需要存一点东西”就默认创建新 SQLite。

### 6.2 JSON / Files

- `portfolio.json`
- `account_profile.json`
- `watchlist.json`
- 研报文件 + index
- daily review cache
- data health event log
- news radar cache
- account execution policy
- A 股交易日历 JSON
- Fact Lake Parquet artifacts

### 6.3 数据安全边界

真实持仓、账户、交易、私密笔记、凭证和模型 key 不进 Git。

当前前端 Settings 的 LLM Provider 配置可能包含浏览器 `localStorage` 中的 provider key；这是**现状描述**，不得与后端 `VR_API_KEY` 混同。`VR_API_KEY` 应作为后端运行时/环境配置，不应复制到浏览器持久化。

---

## 7. 前端 Map

### 7.1 主要页面族

- Daily Review
- Portfolio
- Stock Data
- Decision Cockpit
- Evidence / Thesis
- Trades / Decision Feedback / Performance / Attribution
- Signal Ledger
- Screener
- Sector / Sector Research
- Market History
- Intel
- Data Health
- My Reports
- Notes / Watchlist
- Account Policy
- Settings

### 7.2 核心 lib / stores

- `frontend/src/lib/api.ts`：后端 HTTP client。
- `llm.ts` / `ai-models.ts`：AI provider/model 配置。
- `watchlist.ts`：本地缓存与后端同步。
- `*View.ts`：页面 view-model / formatting。
- `klineIndicatorOverlay.ts` / `technicalIndicatorsView.ts`：技术指标展示。
- zustand stores：AI task / advice request 等交互状态。

### 7.3 Sector Research 静态数据

`frontend/src/data/sectorResearch/` 按 AI computing、CPO、HBM、PCB、semiconductor、smart-driving、solid-state-battery、defense、fusion、humanoid、low-altitude、energy-storage 等行业组织 overview / industry / sources / pricing / value。

---

## 8. Dependency / Call Graph

### 8.1 通用方向

```text
frontend pages
  ↓
frontend lib/api.ts
  ↓
backend router
  ↓
service
  ↓
domain/core + store
```

重要链路示例：

```text
Current Thesis:
campaign binding + Evidence/Thesis ledger
  ↓
formal_thesis_projection adapter
  ↓
formal_thesis_projection_core

Formal Decision:
validated caller inputs
  ↓
frozen_decision_service
  ↓
frozen_decision_store

Account Reality:
trade/account/cash facts
  ↓
position_reality_service
  ↓
account_reality_service
```

### 8.2 关键边界

- `portfolio_advice_policy.POLICY` 是 **Portfolio Advice 子系统内部**政策 source，不是 Formal Decision authority。
- `portfolio_advice_pipeline.validate_portfolio_advice()` 是该 subsystem 的确定性校验执行点。
- 账户资金不应因 AI 输出而改变事实；执行约束必须 deterministic。
- 外部数据失败可以降级，但 UNKNOWN / UNAVAILABLE 不得被包装成 normal。
- 同一 SQLite 文件由多个 store 共用时，必须尊重既有事务与 schema authority。

---

## 9. 运行方式

### 9.1 Backend Linux

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py311.lock.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

### 9.2 Backend Windows PowerShell

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-windows-py312.lock.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900
```

### 9.3 Frontend

```bash
cd frontend
npm ci
npm run dev
```

默认前端 `:5899`，`/api/*` 代理到 `127.0.0.1:8900`。

### 9.4 常见环境变量

- `VR_DATA_DIR`
- `VR_REPORTS_DIR`
- `VR_API_KEY`
- `VR_ALLOW_ORIGINS`
- `VIBE_RESEARCH_REVIEW_DB`
- `VIBE_RESEARCH_TRADE_LEDGER_DB`
- `VIBE_RESEARCH_EVIDENCE_THESIS_DB`
- `VITE_API_URL`
- `TUSHARE_TOKEN`
- `HITHINK_FINANCE_API_KEY`

凭证只从运行环境读取；禁止写入 Git、日志或测试 fixture。

---

## 10. Tests / CI

### 10.1 Backend

```bash
cd backend
.venv/bin/python -m pytest -q tests -m "not live"
.venv/bin/python -m pytest -q tests/test_xxx.py
.venv/bin/python -m py_compile path/to/file.py
```

测试报告必须区分：

```text
LOCAL
EXACT_HEAD_CI
BROWSER_RUNTIME
LIVE_EXTERNAL_DATA
```

没有跑的测试写 `NOT_RUN`，不能用别的层级替代。

### 10.2 Frontend

```bash
cd frontend
npm test
npm run test:e2e:smoke
npm run test:e2e:thesis
npm run test:e2e:data-health
npm run test:e2e:intel-digest
```

### 10.3 CI

当前工作流主要包含：

- Backend tests
- Frontend build & test
- Playwright smoke / domain E2E
- Python Windows lock check
- Whitespace check

受保护 stable 的 required checks 以 GitHub branch protection 的 exact state 为准，不以本 Wiki 的静态列表作为最终 authority。

### 10.4 Validation V2 reference

测试命令这里只负责**导航**。实际执行频率、full-suite budget、CI 与主审职责分工的唯一项目级协议是：

```text
docs/CONVERSATION_HANDOFF.md §4.2 VALIDATION_V2
```

不要从本节的 full-suite 命令存在性推导“每次修改都必须运行全量测试”。

---

## 11. 关键工程纪律摘要

1. **Fail Closed**：账本损坏、身份矛盾、unknown eligibility、schema/version 异常等高价值事实必须 fail closed。
2. **UNKNOWN 保持 UNKNOWN**：absence 不能推导 healthy / clear / none。
3. **数据安全**：真实持仓、账户、交易、凭证、私密笔记不得进 Git；任何 key 不进源码、日志、测试快照。
4. **Formal immutability**：Original Thesis / Frozen Decision / append-only Outcome 不允许用 living-object overwrite 模式替代。
5. **Git discipline**：不 direct push stable、不 force push、不对已 push commit amend/rebase；修正用新 commit。
6. **AI boundary**：AI 不修改 Canonical Fact、Original Thesis、Frozen Decision，不绕过 deterministic gate，不自动交易。
7. **Authority before convenience**：性能更好、API 更方便、本地已有值，都不能自动获得 semantic authority。
8. **Validation discipline**：targeted-first；重复 full-suite 不是严谨性的替代品；exact-head CI 与 independent semantic review 分工独立。

---

## 12. API Map（导航级）

主要 API family：

- `/api/health`
- `/api/daily-review*`
- `/api/portfolio*`
- `/api/account*`
- `/api/cash-events*`
- `/api/position-reality*`
- `/api/campaigns*`
- `/api/evidence*`
- `/api/theses*`
- `/api/decision-feedback*`
- `/api/decision-evidence*`
- `/api/signal-ledger*`
- `/api/decision-analytics*`
- `/api/trade-ledger*`
- `/api/performance-attribution*`
- `/api/decision-cockpit/*`
- `/api/data-health*`
- `/api/intel-digests*`
- `/api/watchlist`
- `/api/myreports*`
- `/api/account-execution-policy`
- `/api/quote` / `/api/kline` / `/api/financials` / `/api/valuation*` / `/api/reports` / `/api/news` 等个股数据族
- `/api/market/*`
- `/api/global/*`
- `/api/sector-research/*`
- `/api/technical-indicators/*`
- `/api/screener/*`
- `/api/bk11-history/*`
- `/api/alert-rules*`
- `/api/chat`

精确 endpoint、request/response schema 与 HTTP status 必须查看 exact-head router/app/tests。

---

## 13. 维护规则

- 本文件是 **Engineering Navigation Index / Anti-Rewheel Index**，不是授权文档，也不是 semantic authority。
- 每次正式更新 Wiki 必须刷新顶部 `Snapshot Branch / Snapshot Head / Snapshot Date`；禁止只写“当前 stable”而没有 full SHA。
- **只在结构性变化时更新**：新增/删除 subsystem、Semantic Authority ownership 改变、新增数据库/表族、新增 router family、重要 dependency direction 改变、Authority Map 中 `MISSING → IMPLEMENTED` 或 existing authority 被替换。
- 普通 bugfix、测试数量变化、内部函数重构、短生命周期 worktree/CI/本地状态**不要求**更新 Wiki。
- PR 尚未进入 stable 时，不得把 Draft 实现写成 `IMPLEMENTED_IN_STABLE`；需要提及时必须明确 `IN_FLIGHT / NON-STABLE`，并避免让短生命周期 PR 状态污染长期地图。
- 文件数、测试数、页面数等统计只是 Snapshot 导航信息；过期不构成架构 blocker。
- 任何 Agent 使用本 Wiki 开发时，必须执行 §0.4 Anti-Rewheel Preflight；Wiki 中命中一个模块只能作为“去哪里验证”的线索，不能替代 source inspection。
- Validation 规则不要复制进 Wiki；只引用 `CONVERSATION_HANDOFF.md §4.2`，避免形成第二份会漂移的执行协议。

---

## 14. 结构性更新 Checklist

当某个 PR 准备改变仓库结构时，主审检查：

```text
[ ] 新增/删除 Semantic Authority？
[ ] Authority owner 发生改变？
[ ] 新增 DB / table family？
[ ] 新增 router/API family？
[ ] 改变重要 dependency direction？
[ ] 某个 MISSING capability 进入 stable IMPLEMENTED？
[ ] 某 legacy subsystem 被正式降级/替代？
```

任一项为 YES，应在对应结构性合并波次同步本 Wiki；全部为 NO，则默认不要求 Wiki churn。
