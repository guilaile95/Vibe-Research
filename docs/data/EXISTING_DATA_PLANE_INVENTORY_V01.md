# Existing Data Plane Inventory V0.1（DS-R1）

> Owner：DeepSeek / D · Mode：Docs / Inventory / Architecture Evidence Only
> 日期：2026-08-10
> 本文档是**纯盘点**：不设计 DS-A1 contract、不实现 DS-L1、不新增 provider、不修改生产代码。

## 0. 证据基线

| 项 | 值 |
|---|---|
| EVIDENCE_STABLE_HEAD | `1be2ecba505a8108740c311c103a2c72d3bcd444` |
| 基线引用 | `feature/research-system-v01`（远程 HEAD） |
| 验证方式 | 工作树 `backend/` 与基线逐字节一致（`git diff 1be2ecba -- backend/` 为空）；north-star 分支 `67e1da2e` 仅含 governance 文档修正，backend/frontend/a-stock-data 代码域与证据基线一致 |
| STABLE_HEAD_PINNED | **PASS** |

**事实来源优先级**：本文所有「CURRENT / INTEGRATED」陈述均指可从 `1be2ecba` 可达的代码；未 pin 的本地工作树不作为当前事实。

---

## 1. CURRENT vs IN-PROGRESS 分离

显式能力状态定义：

- `INTEGRATED_STABLE`：可从证据基线 app.py 路由 / 生产路径可达
- `ACCEPTED_NOT_MERGED`：已接受但未合并入证据基线的分支
- `IN_PROGRESS`：进行中、未集成
- `RESEARCH_ONLY`：仅文档/技能包，运行时零引用
- `NOT_IMPLEMENTED`：不存在实现
- `UNKNOWN`：证据不足

| 能力 | 状态 | 说明 |
|---|---|---|
| 7 条生产数据链（腾讯行情 / 东财五域 / akshare / mootdx / 港美股 gstock / HKEX 北向 / RSS 资讯雷达） | **INTEGRATED_STABLE** | 经 `app.py` 路由接入 |
| Tushare Pro 客户端 + facts_adapter + ingestion_service + CLI | **ACCEPTED_NOT_MERGED**（模块完整、有单测，但仅 CLI 接入） | `tushare_pro_client.py` docstring 明示不在 GET / 应用启动 / Daily Review / history API / Data Health 中调用；其下游 `short_term_fact_store` + `bk11_history_service` 已经 `bk11_history_router`（app.py:176）生产接入 HTTP |
| Phase 2 Formal Thesis 相关测试/功能分支（如 `test/p0-formal-thesis-concurrency-v0.1` 等） | **ACCEPTED_NOT_MERGED** | 与数据平面无直接交集，单独识别 |
| PR #79 HiThink probe / DS-A1 | **IN_PROGRESS / NOT_INTEGRATED** | 未进入证据基线 |
| `a-stock-data/`、`global-stock-data/` 技能包 | **RESEARCH_ONLY** | 仅文档/SKILL；backend 运行时零引用 |
| `IWENCAI_API_KEY` / `VR_DATA_PROXY`（.env.example） | **RESEARCH_ONLY** | backend 源码零引用，占位未实现 |
| fund / institutional holdings 数据集 | **NOT_IMPLEMENTED** | 无外部机构持仓数据路径（代码中的 holdings 仅为用户自身 `portfolio.json`） |

CURRENT_VS_IN_PROGRESS_SEPARATED = **PASS**（未将未合并分支混入当前架构）。

---

## 2. Provider Ingress 盘点

### 2.1 Provider 总表

| provider_id | 入口 module/symbol | network/local | credential | 集成状态 |
|---|---|---|---|---|
| tencent_gtimg | `astock.tencent_quote` / `_fetch_gtimg`（astock.py:43-94）、`astock.index_quote` | network（`qt.gtimg.cn`，仅标准库） | 无 | INTEGRATED_STABLE |
| eastmoney_push2 | `astock.a_share_snapshot` / `market_turnover_rank` / `board_ranking`（astock.py:682-850,599-624,900+）；`gstock._push2_stock_get` | network | 无 | INTEGRATED_STABLE |
| eastmoney_reportapi | `astock._report_session`（astock.py:116+，`reportapi.eastmoney.com/report/list`） | network | 无 | INTEGRATED_STABLE |
| eastmoney_datacenter | `astock.dividend_history`/`lockup_expiry`/`block_trade`/`holder_num_change`/`dragon_tiger_board`/`margin_trading`（`RPT_*`）；`gstock._key_metrics` | network | 无 | INTEGRATED_STABLE |
| eastmoney_push2ex | `astock.em_zt_topic_pool`（getTopicZTPool/ZBPool/DTPool/YesterdayZTPool）；`short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot` | network | 无 | INTEGRATED_STABLE（池）；生产 final 生产者经 CLI 路径 |
| akshare（惰性） | `astock._akshare()` 第 3/4/5 层（一致预期/新闻/公告、`stock_financial_abstract_ths`、`stock_fund_flow_industry`、`valuation_percentile` 经百度） | network | 无 | INTEGRATED_STABLE（惰性依赖，缺失抛 `DependencyMissing`） |
| mootdx（惰性） | `astock.kline`（`Quotes.factory(market="std")`，TDX 协议）、`astock.finance` | network | 无 | INTEGRATED_STABLE（惰性） |
| gstock（东财域内港美股） | `gstock.us_hk_stock` / `global_indices` / `_key_metrics` | network | 无 | INTEGRATED_STABLE（Yahoo/SEC 不并入） |
| hkex_official | `northbound_capital_flow.get_northbound_capital_flow`（HKEX Stock Connect Daily Statistics JS） | network | 无 | INTEGRATED_STABLE |
| rss_newsradar | `newsradar.py`（`news_sources.json` 多 RSS） | network | 无 | INTEGRATED_STABLE |
| cninfo（akshare） | `astock.disclosure` | network | 无 | 稳定主链的备用；标记不稳定 |
| tushare_pro | `tushare_pro_client.TushareClient.query`（allowlist: daily/suspend_d/stk_limit/stock_basic）；`bk11_tushare_facts_adapter`；`bk11_tushare_ingestion_service` | network（`api.tushare.pro`） | **`TUSHARE_TOKEN`**（env，tushare_pro_client.py:30,63） | **ACCEPTED_NOT_MERGED**（仅 CLI） |
| local_static | `backend/data/cn_a_share_trade_calendar_v01.json`（trade_calendar.py） | local | 无 | INTEGRATED_STABLE |

### 2.2 Credential 汇总（源码实际存在）

| 变量 | 用途 | 读取处 |
|---|---|---|
| `TUSHARE_TOKEN` | tushare_pro 唯一 token | tushare_pro_client.py:30,63 |
| `VR_DATA_DIR` | 本地存储目录覆盖 | short_term_fact_store.py:106 等 |
| `VR_API_KEY` | 全站可选鉴权 | app.py:197 |
| `VR_ALLOW_ORIGINS` | CORS 白名单 | app.py:147 |
| `VIBE_RESEARCH_NEWS_RADAR_CACHE` | 资讯雷达缓存路径覆盖 | newsradar.py:25,30,38 |
| `VIBE_RESEARCH_ALERT_RULE_DB` / `VIBE_RESEARCH_CAMPAIGN_DB` | 本地 DB 路径覆盖 | alert_rule_store.py:88 / campaign_store.py:232 |

> 注意：`.env.example` 的 `IWENCAI_API_KEY`、`VR_DATA_PROXY` 在 backend 源码**零引用**，为占位。不要从库安装推断 provider 能力——本盘点全部以源码实际调用为准。

### 2.3 Data Health 集成面

`quotes`/`announcements`/`financials`/`sector_research`/`northbound_capital_flow`/`technical_indicators`/`top_risk_analysis` 由业务调用点写健康事件；`news_radar`/`bk11_history`/`northbound_capital_flow` 等有只读 adapter。**tushare_pro 自身无 health 监控**（其产物 `bk11_history` 有）。

PROVIDER_INGRESS_INVENTORIED = **PASS**。

---

## 3. Dataset-Level Matrix（决策相关结构化数据集）

存在 18/19；**NOT_PRESENT：fund/institutional holdings**。以下为存在项摘要（JSON 交付含完整结构化字段）。

| dataset_candidate_id | module/symbol | provider | fetch_semantics | history_mode | 关键时间字段 | adjustment | PIT | storage/cache | Data Health | 跨源对账 |
|---|---|---|---|---|---|---|---|---|---|---|
| ds_daily_history_price | `astock.kline`（category 4/5/6/11） | mootdx (TDX) | rolling window | snapshot_with_backfill | `datetime`/`date` | **无复权** | 否 | 内存 TTL | quotes/technical_indicators | 无 |
| ds_snapshot_price | `astock.tencent_quote`/`a_share_snapshot`/`index_quote`/`market_turnover_rank`；`gstock.us_hk_stock` | 腾讯 gtimg；东财 push2 | snapshot | snapshot_only | 无行内时间；envelope `fetched_at` | n/a | 否 | 内存 TTL（market._cached 300s） | quotes/portfolio_quotes | 无 |
| ds_trading_calendar | `trade_calendar.previous_trade_date`；`backend/data/cn_a_share_trade_calendar_v01.json` | SSE/SZSE 官方共识离线工件 | by_date | snapshot | `sessions[]`、`generated_at`、`source_checked_at`、`sources[].announcement_date/.retrieved_at/.verification_status` | n/a | **是**（确定性离线） | 仓库 JSON | freshness 规则 | SSE+SZSE 年度共识强制 |
| ds_market_breadth | `market.calculate_market_breadth`（astock.a_share_snapshot 派生） | 东财 push2（派生） | snapshot | snapshot_only | envelope `fetched_at` | n/a | 否 | 内存 TTL | daily_review 核心、portfolio gate | 无（Tushare 另算一版） |
| ds_limit_up_pool | `astock.em_zt_topic_pool`；`short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot`；`short_term_limit_up_final_snapshot.fetch_final_limit_up_pool_snapshot` | 东财 push2ex | by_date（YYYYMMDD） | snapshot_with_backfill（仅 daily-facts envelope 内持久化） | `requested_trade_date`、`observed_at`、行 `stock_code`+`lbc` | n/a | 已完成交易日**是** | 内存 + fact_snapshots JSON | bk11_history、daily_review emotion | **是**（v0.2 Tushare vs 东财 count） |
| ds_limit_up_ladder_gap | `short_term_limit_up_ladder.compute_limit_up_ladder`；`short_term_ladder_gap.compute_ladder_gap` | 派生（pool lbc） | snapshot | snapshot（envelope 内） | `trade_date`、`session`、`fetched_at`、`snapshot_at`、`is_final` | n/a | 单日内 PIT 是 | fact_snapshots envelope | bk11_history | 经 v0.2 组合层 |
| ds_sector_industry_facts | `astock.board_ranking("industry"/"concept"/"region")`、`industry_comparison`、`concept_blocks`、`sector_research_data` | 东财 clist/slist/reportapi | snapshot | snapshot_only | 无 | n/a | 否 | 内存 TTL（board 100 名缓存） | sector_research | 无 |
| ds_sector_capital_flow | `market._sectors`（`astock._akshare().stock_fund_flow_industry`） | akshare→东财/同花顺 | snapshot | snapshot_only | 无 | n/a | 否 | 内存 TTL（overview） | 无（在 overview 内） | 无 |
| ds_northbound_capital_flow | `northbound_capital_flow.get_northbound_capital_flow`/`get_northbound_history` | HKEX 官方（SOURCE_TIER=authoritative） | by_date | snapshot_with_backfill（按需，无持久化） | `trade_date`（仅取自 payload）、`fetched_at` | n/a | **是**（按日） | 内存 | northbound_capital_flow adapter | 显式拒绝东财 net-buy（fail-closed 边界，非对账） |
| ds_valuation | `astock.valuation_percentile`（百度）；`full_valuation`/`profit_forecast`（腾讯+同花顺） | 百度/腾讯/同花顺 | by_date-ish（序列取当前百分位） | snapshot_with_backfill | 序列日期轴；`eps_26e/eps_27e` | n/a | 部分 | app `_PCT_CACHE`（1800s） | 无 | 无 |
| ds_financial_statements | `astock.financials`（同花顺最新期）；`astock.finance`（mootdx，营收不可靠）；`gstock._key_metrics`（东财） | 同花顺/mootdx/东财 | snapshot | snapshot_only（`df.iloc[-1]`） | `period`/`报告期`/`REPORT_DATE` | n/a | 否 | 内存 | financials（REPORTING_PERIOD） | mootdx vs 同花顺差异有文档 |
| ds_corporate_actions | `astock.dividend_history`/`lockup_expiry`/`block_trade`/`holder_num_change`/`dragon_tiger_board` | 东财 datacenter | by_date | snapshot_with_backfill | `EX_DIVIDEND_DATE`/`FREE_DATE`/`TRADE_DATE`/`END_DATE`（[:10]） | 仅原始事实，**不应用到价格序列** | 部分 | 内存 | 无 | 无 |
| ds_instrument_universe | 东财当前全 A（`a_share_snapshot`）；Tushare `stock_basic` 历史池（list_status L/D/P/G） | 东财 push2 / Tushare | snapshot / by-date pool | snapshot_only / snapshot_with_backfill | `list_date`、`delist_date` | n/a | Tushare 池**是**（`T < delist_date`，boundary_uncertain） | 内存 | bk11_history | Tushare 内 universe 对账（unexplained/out_of_pool） |
| ds_index_concept_membership | `astock.concept_blocks`/`board_ranking`/`hot_concepts` | 东财 | snapshot | snapshot_only（成员漂移不捕获） | 无 | n/a | 否 | 内存 | 无 | 无 |
| ds_sentiment_emotion | `market._emotion`/`_sentiment`/`get_short_term_emotion` | 东财 push2ex（派生） | snapshot（回溯 ≤8 日解最近交易日） | snapshot_only | `date`、`zt_count/dt_count/zb_count`、ladder 等 | n/a | 部分（最近日解析） | 内存 TTL 300s | daily_review emotion | 无 |
| ds_top_risk_signals | `top_risk_service.analyze_top_risk`；`top_risk_config.yaml` | 派生（astock 多源） | snapshot | snapshot_only | `trade_date`（末 K 线）、`fetched_at`、`input_fingerprint` | n/a | 否 | TTL 900s + decision_trace.sqlite3 | top_risk_analysis | 多源无对账 |
| ds_news_announcements | `astock.stock_news`/`announcements`/`disclosure`；`newsradar.py`；`intel_digest_service` | 东财/cninfo/RSS | by_date/snapshot | snapshot_with_backfill（radar 按次缓存；intel 按 digest_date 持久化） | `notice_date`/`published_at`/`pubDate`/`generated_at`/`digest_date` | n/a | 部分 | radar.json 缓存 + intel_digest.sqlite3 | news_radar/announcements | newsradar 多 RSS；intel fingerprint 去重 |
| ds_margin_block_trade | `astock.margin_trading`（RPTA_WEB_RZRQ_GGMX）；`astock.block_trade`（RPT_DATA_BLOCKTRADE） | 东财 datacenter | by_date | snapshot_with_backfill | `DATE`/`TRADE_DATE`（[:10]）、margin/block 字段 | n/a | 部分 | 内存 | 无（经 top_risk） | 无 |

**观测结论**（证据约束，未猜测）：
- **无市场数据持久化**存在于高频/实时数据集（K线/快照/广度/板块/北向/情绪/融资融券）：全部 fetch-on-demand + 进程内 TTL。唯一持久化的市场结构化数据是 BK-11 daily-facts envelope（A5/A6，`short_term_facts.sqlite3`）与离线交易日历（A3）。
- **PIT 安全**仅在：日历（确定性）、涨停池/final producer（已完成交易日）、北向（按日）、Tushare universe 池（list/delist）。其余全部 snapshot-only，无法 as-of 重建。
- **复权完全缺失**：`astock.kline` 不除权；分红/转股为原始事实，从不应用到价格序列。
- **跨源对账仅一处**：`short_term_daily_facts_v02` Tushare limit_up_count vs 东财 row_count（容差 3 / 5%）。

DATASET_MATRIX_COMPLETE_FOR_DISCOVERED_SCOPE = **PASS**
TEMPORAL_SEMANTICS_NOT_GUESSED = **PASS**（时间字段全部来自代码实际读取，语义按证据标注）
UNKNOWN_PRESERVED = **PASS**（未证实的语义一律写 UNKNOWN）

---

## 4. Storage / Cache 盘点

### 4.1 SQLite stores

| store | purpose | writer | append/mutable | schema/version | DS-L1 可复用 | operational-only |
|---|---|---|---|---|---|---|
| `short_term_facts.sqlite3`（short_term_fact_store.py） | BK-11 daily-facts envelope（v0.1/v0.2）持久化 | `save_daily_facts`/`save_daily_facts_monotonic`（经 ingestion_service） | append + monotonic 质量规则（insert/dedup/upgrade/block；never downgrade） | `schema_meta`（short-term-fact-store-v0.1）；表 `fact_snapshots` PK (trade_date, session) | **是——canonical fact store** | 是（显式 ingestion，无自动调度） |
| `decision_trace.sqlite3`（decision_trace_store + signal_ledger_store） | decision runs + evidence + explanation + signal ledger + outcomes | portfolio_advice 管线、top_risk_trace_service、signal ledger | append + 幂等改写（ON CONFLICT DO UPDATE；evidence/explanation 每 run 删重建） | `schema_meta`（decision_trace_v1） | **是**（决策审计） | 是 |
| `intel_digest.sqlite3` | AI 每日情报摘要 | intel_digest_service | insert-only + dedup（DO NOTHING） | 无 schema_meta；UNIQUE(digest_date, sector_key, input_fingerprint) | **是** | 是 |
| `trade_ledger.sqlite3` + `account_event_store.py` | 交易执行 + 账户事实链 | trade_ledger/account_event service | append + soft-void（voided_at） | 惰性建表 | **是** | 是 |
| 共享 review DB（review_store.py） | daily review 快照 + decision cockpit | review_history/decision_cockpit | append；同日多版本（UNIQUE(trade_date, payload_hash)） | `daily_review_snapshots` 等 | **是** | 是 |
| `decision_feedback.sqlite3` | 建议结果反馈 | decision_feedback_service | append + void | `decision_feedback` PK feedback_id | **是** | 是 |
| `ai_generated_results`（ai_result_store.py） | 校验后的 AI 结果 | ai_result_service | upsert per (result_type, trade_date) | PK (result_type, trade_date) | **是** | 是 |
| `performance_attribution.sqlite3` | P&L 归因快照 | performance_attribution_service | append | 多表 | **是** | 是 |
| `alert_rules.sqlite3` / `campaigns.sqlite3` | 告警规则 / 活动生命周期 | 各自 service | versioned / append+transitions | schema_meta | 部分 | 是 |
| `evidence_thesis.db`（evidence_thesis_store.py） | 投资逻辑与证据账本 | evidence_thesis_service | append + versioned revision + soft delete | schema_meta（evidence_thesis_ledger_v1）| integrity_check + backup | **是**（用户内容，不重审 Formal 细节） | 是 |

### 4.2 JSON / filesystem 持久化

`data_health_events.json`（运营事件）、`cn_a_share_trade_calendar_v01.json`（离线日历）、`daily_review_latest.json`（质量门控磁盘缓存）、`watchlist.json`（原子 + SHA256 etag）、`portfolio.json`（用户持仓）、`backend/.cache/radar.json`（资讯雷达）、`myreports/index.json` + PDF、`top_risk_config.yaml`、`news_sources.json`。全部 atomic 写 + fail-closed 校验。

### 4.3 Memory caches

`market._cached`（300s 全站共享）、`daily_review._review_cache`（300s single-flight）、`app.TTLCache`（LRU max 512：_DC/_PCT/_ANN/_FIN）+ `app.CachedDiscovery`（FIFO 20min）、`top_risk_service._CACHE`（900s per (code,days,config_hash)）、`ai_result_service._cached_display_trade_date`。

**CSV / Parquet：项目内不存在。**

STORAGE_CACHE_INVENTORIED = **PASS**

---

## 5. Data Health 复用图

### 5.1 现有能力（证据基线内，全部实际接线）

- **架构**：`data_health_service.py`（规范层：21 字段 `DataHealthRecord`、`SOURCE_REGISTRY` 15 源、错误码→安全文案映射、三态、freshness 辅助、事件状态机、聚合） + `data_health_adapters.py`（15 个只读 concrete adapters + Protocol + `AdapterReadError` 4 稳定码 + 严格校验 + `collect_all_records`/`get_health_overview`） + `data_health_event_store.py`（单文件 JSON 事件存储，`data-health-events.v1`，原子写） + `data_health_router.py`（只读 GET API）。
- **wired adapters（15）**：DailyReview / PortfolioAdviceGate / PortfolioQuotes / Quotes / Announcements / Financials / NewsRadar / SectorResearch / MyReports / WatchlistPortfolioStorage / EvidenceLedger / NorthboundCapitalFlow / TechnicalIndicators / TopRiskAnalysis / Bk11History。与 `SOURCE_REGISTRY` 严格对齐（数量、顺序、module/display_name 校验）。
- **已提供**：provider/module availability（normal/partial/unavailable）；freshness（`is_stale` + `stale_after_seconds` + 交易日历规则）；coverage（`coverage_current/expected`，多数事件源为 null）；reason codes（12 稳定公开码：SOURCE_NOT_INITIALIZED/STALE/PARTIAL/UNAVAILABLE/CORRUPTED/SCHEMA_INCOMPATIBLE/TIMEOUT/DEGRADED + 4 gate 业务码）；degraded/unavailable；read-only health 行为（adapter 层严格只读）；source metadata（SOURCE_REGISTRY / SOURCE_CALCULATION / SOURCE_RELATED_PAGES / detail_path）。
- **只读性**：adapter 严格只读；事件**写入**由业务调用点执行（`app.py`/`portfolio.py`/`portfolio_advice_service.py`/`top_risk_service.py`/`technical_indicators_router.py`），全部 `safe_call` 吞异常，写失败不影响业务。event store 属运营元数据。

### 5.2 DS-A1 / 未来 Fact 级治理真正新增什么

| 缺口 | 分类 | 说明 |
|---|---|---|
| 数据集级可用性（per-dataset 而非 per-source_id） | **NEW_CONTRACT_REQUIRED** | 现有健康按 `source_id`（模块级），DS-A1 需 dataset 级 availability 契约 |
| 观测级 freshness / 时效（by_date + fetched_at vs trade_date 分离） | **EXTEND_EXISTING** | 现有 freshness 规则可扩展至观测元数据 |
| per-observation provenance 结构化（provider_id/temporal/revision） | **NEW_CONTRACT_REQUIRED** | 健康系统只有事件时间戳，无观测来源结构 |
| revision / restatement 健康状态 | **EXTEND_EXISTING** | 可复用 reason code 体系扩展 |
| PIT / as_of 查询正确性健康 | **DEFER** | 依赖 Fact Lake 读路径先存在 |
| 现有覆盖监控缺口补全（多数事件源 coverage=null） | **EXTEND_EXISTING** | 直接扩展现有 record 字段 |

**明确：不替换 Data Health。** 全部分类如上，DS-A1 是新契约而非替代。

DATA_HEALTH_REUSE_MAP = **PASS**

---

## 6. Fallback / Routing / Reconciliation 图

### 6.1 Provider fallback（同数据集换 host/源）

| 位置 | 触发 | 行为 | 混同？ |
|---|---|---|---|
| `astock.a_share_snapshot`/`board_ranking`/`market_turnover_rank`（astock.py:682-850,900+,599-624） | 首页 push2 失败 | `push2.eastmoney.com` → `push2delay.eastmoney.com` 双 host 探测 + latch；分页有界重试（max 3, backoff） | 否——同源双 host，标注「延时行情」，不视为验证 |
| `gstock._push2_stock_get`（gstock.py:38-51） | push2 掉连 | 按 `_gs_host` latch 降级 push2delay | 否 |
| `astock` Layer 3/4/5（akshare/mootdx） | 依赖缺失 | 抛 `DependencyMissing`，无运行时 fallback | — |
| `daily_review._pass_envelope` `fallback_source` | env 非 dict | 仅设默认标签 `eastmoney_push2`，非 provider 切换 | 命名有误导，实为默认标签 |

### 6.2 Dataset-level routing（按数据集选源）

| 位置 | 行为 |
|---|---|
| `astock.financials`（:297-319） | 财务摘要**静态路由到同花顺**（mootdx finance 营收不可靠） |
| `astock.valuation_percentile`（:322） | 路由到百度股市通 |
| `bk11_tushare_facts_adapter` + `short_term_daily_facts_v02`（:40-45） | **组合双源**：facts 段 Tushare，ladder 段东财 final producer |
| `short_term_daily_facts_v02.compute_daily_facts_v02`（:233-247） | 数据集级替换：Tushare 合法零涨停证明替代东财 producer（`legal_zero is True AND limit_up_count == 0` 双重门控，ladder_source_ids=["tushare_daily"]） |
| `gstock`（:1-11） | 港美股仅并入东财域内子集，Yahoo/SEC 不并入 |

### 6.3 Cross-source verification（跨源比对）

| 位置 | 行为 |
|---|---|
| **`short_term_daily_facts_v02`（:277-287）——唯一真正跨源验证** | producer normal 时 `em_count` vs `ts_count`；`abs(ts-em) > max(3, em*0.05)` → `CROSS_SOURCE_COUNT_MISMATCH`；有 cross_codes → overall 至少 partial |
| `short_term_limit_up_final_snapshot`（:43-44） | 同一东财源连续 3 观测 + 指纹一致 = 时间稳定性确认（非跨源） |
| `position_reality_service.reconcile_positions` / `account_reality_service._cash_reconciliation` | ledger vs portfolio 对账（MATCH/MISMATCH/…），属账户域 |

### 6.4 关键结论

**源码层面没有把 provider fallback 与 cross-source verification 当一回事。** 两者边界清晰：push2→push2delay 是显式标注的延时行情降级，不宣称验证；唯一跨源验证用独立 code `CROSS_SOURCE_COUNT_MISMATCH` 记录并降级，**不替换数据、不重算**。`empty_ladder_proof` 是受双重门控的证明式替换，非静默混同。

FALLBACK_ROUTING_RECONCILIATION_MAP = **PASS**

---

## 7. Duplication Hotspots

| 热点 | exact files/symbols | 重复内容 | 有意？ | 风险 | 分类 |
|---|---|---|---|---|---|
| H1a 涨停池双入口 | `astock.em_zt_topic_pool`（astock.py:541-554）vs `short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot`（:385,467-478） | 同一 push2ex URL+params 两套请求构造；缓存独立 | 部分（adapter 需 fail-closed 合同） | 中（重复请求/口径漂移） | CONSOLIDATE_LATER |
| H1b 行业板块排名双实现 | `astock.board_ranking`（:900-1040）vs `industry_comparison`（:1287-1306） | 同文件内同一 clist 事实两个独立实现 | 否（历史遗留） | 中低 | REUSE_EXISTING |
| H1c/H1d 跨源宽度/涨停口径 | `market.calculate_market_breadth` vs `bk11_tushare_facts_adapter`（:330-347）；涨停家数 3 套（market zt_count / Tushare limit_up_count / 东财 row_count） | 同一事实多口径 | 有意双源但无统一注册 | 中 | **DS_A1_BOUNDARY_NEEDED** |
| H2 代码规范化多路径 | `_CODE_RE`/`^\d{6}$` 13+ 文件；`validate_and_normalize_codes`（screener_models:157）vs `_normalize_codes`（watchlist_store:66）；多市场规则 evidence（:151-210）vs gstock（:126-141） | 校验+strip+去重骨架多份；HK/KR 规则两处 | CN-only 与 multi-market 范围差异有意 | 中（规则漂移，含无锚 regex） | REUSE_EXISTING |
| H3 日期/UTC 解析多路径 | `_DATE_RE` 等 ~25 处；`_strict_parse_date` 4 份；`_parse_utc` 4 份；内联 `replace("Z","+00:00")` ~10 处；kline 规范化 `_parse_klines`（technical_indicators:39）vs `_normalize_kline`（top_risk_service:163） | 同构解析/规范化多份复制 | 多数无注释 | 中 | CONSOLIDATE_LATER |
| H4 缓存抽象多套 | `app.TTLCache`（:1448）+ `app.CachedDiscovery`（:1806）+ `market._cached` + `trade_calendar._calendar_cache`；磁盘 `daily_review_cache` vs `newsradar` cache | TTL/LRU/原子写模式多套独立实现 | 独立演进，无复用声明 | 中低 | CONSOLIDATE_LATER |
| H5 源健康状态/错误码多套 | `DataHealthStatus` Literal 多处（data_health_service:9 / alert_rules:59 / top_risk_schema:19 / bk11_history:34）；错误码集合 3 套 | 同名同值状态/码集重复声明 | 部分有意 | 中 | REUSE_EXISTING |
| H6 provider wrapper | Tushare：唯一 `TushareClient`，各模块复用（**NOT_DUPLICATED**）；东财共享传输 `em_get` 复用良好，仅 H1a/H1b 例外 | — | — | — | KEEP_SEPARATE |
| H7 对账逻辑 | `short_term_daily_facts_v02`（唯一跨源）vs `portfolio_advice_fact_reconciler`（权威单源重算）vs `short_term_fact_compare`（同源描述差异）vs `review_compare` | 四者域不同，非同一逻辑多份 | 是 | 低 | KEEP_SEPARATE |
| H8 数据身份串分散 | `SCHEMA_VERSION` ~30 处；`"eastmoney_getTopicZTPool"` 等身份串跨模块重复字面量；无统一 provider_id 常量 | 版本/身份字面量散落 | 否 | 中低 | CONSOLIDATE_LATER |
| 附加 | `_normalize_reason_codes` 5 份（词表不同→KEEP_SEPARATE）；`_num`/`_optional_float` 等数值归一化 ≥7 模块（REUSE_EXISTING） | — | — | 中低 | 见各条 |

DUPLICATION_HOTSPOTS_IDENTIFIED = **PASS**（本轮不修复任何热点）

---

## 8. DS-L1 复用边界

| 类别 | 结论 | 证据 |
|---|---|---|
| **Data Health（freshness/coverage/reason codes）** | ALREADY_HAVE | data_health_service/adapters（15 adapter、12 reason code） |
| **fact store SQLite 模式（WAL + append + monotonic + schema_meta）** | ALREADY_HAVE | short_term_fact_store.py |
| **envelope 级 provenance（source_ids/reason_codes/limitations）** | ALREADY_HAVE | short_term_daily_facts_v02 / pool_adapter 合同 |
| **日历工件 + 严格校验 + 官方来源 consensus** | ALREADY_HAVE | trade_calendar.py + data/ JSON |
| **北向权威边界（fail-closed、limitations、SOURCE_TIER）** | ALREADY_HAVE | northbound_capital_flow.py |
| **Tushare universe 池 list/delist + boundary_uncertain** | ALREADY_HAVE | bk11_tushare_facts_adapter |
| **decision_trace 持久化（fingerprint/decision_run_id）** | ALREADY_HAVE | decision_trace_store.py |
| **BK-11 daily-facts store → 原始不可变观测层** | **EXTEND** | 已按 (trade_date, session) append；需补 by_date 观测身份 + revision 字段 |
| **per-observation provenance 结构化（provider_id/temporal/as_of）** | **EXTEND** | 已有 envelope 级；需下沉到观测级 |
| **Provider transport（em_get / tushare client / 腾讯 stdlib）** | EXTEND（封装复用，不重写） | astock/gstock/tushare_pro_client |
| **Normalization（代码/日期/数值）** | EXTEND（收敛复用） | 见 H2/H3 热点 |
| **Cross-source reconciliation 框架** | EXTEND（目前仅 1 点） | short_term_daily_facts_v02:277-287 |
| **Raw immutable observation 层（高频数据零持久化）** | **NEW_FOR_FACT_LAKE** | 见 §3：K线/快照/广度/板块/北向/情绪/融资融券全无持久化 |
| **Dataset identity / provider_id 注册表** | **NEW_FOR_FACT_LAKE** | 现无统一身份（H8） |
| **Temporal contract（fetch_semantics/history_mode/as_of）** | **NEW_FOR_FACT_LAKE** | 各数据集各自表述，无统一契约 |
| **PIT query（as_of 回溯读）** | **NEW_FOR_FACT_LAKE** | 现无 as_of 读路径 |
| **Revision detection** | **NEW_FOR_FACT_LAKE** | 仅 v0.2 count 差异；无逐观测 revision 检测 |
| **Adjustment / 复权** | **NEW_FOR_FACT_LAKE** | `astock.kline` 无复权；分红原始事实未应用 |
| **Historical universe / survivorship** | **NEW_FOR_FACT_LAKE** | 仅 Tushare 池处理 list/delist |
| **Operational metadata（event store 等）** | **DO_NOT_MOVE_TO_LAKE** | data_health_events.json |
| **User content（evidence_thesis / portfolio / watchlist / myreports）** | **DO_NOT_MOVE_TO_LAKE** | 用户内容，非市场事实 |
| **Decision/feedback/analytics/alert/campaign/attribution 业务 store** | **DO_NOT_MOVE_TO_LAKE** | 业务状态，非数据平面 |
| **daily_review_cache** | **DO_NOT_MOVE_TO_LAKE** | 展示层磁盘缓存 |

DS_L1_REUSE_BOUNDARY = **PASS**（未在证据不足处强推结论）

---

## 9. DS-L1 Candidate Shortlist（仅供 PoC 参考，非最终选择）

按 1) Thesis/Decision 可复现收益 2) 时间/PIT/revision 价值 3) 现有可复用代码量 4) 实现隔离度 5) provenance 重要性 综合排序。

| 排名 | candidate | 理由 | 主要 gap | 建议路径 |
|---|---|---|---|---|
| 1 | **ds_limit_up_pool_ladder**（BK-11 daily facts） | 已有持久化 store + envelope provenance + PIT（已完成交易日）+ revision/legal-zero 检测 + 跨源对账点 | 观测级 provenance 下沉；revision 逐观测化 | EXTEND |
| 2 | **ds_daily_history_price**（K线） | Thesis/Decision 复现价值最高 | 无持久化、无复权、无 PIT、无 revision——是最大真缺口，PoC 能证明「adjustment/revision」痛点 | NEW_FOR_FACT_LAKE |
| 3 | **ds_northbound_capital_flow** | 权威源、by_date、PIT、provenance 纪律已强 | 无持久化（内存 only） | EXTEND |
| 4 | **ds_instrument_universe**（Tushare pool） | 已处理 list/delist + boundary；PIT universe | 无持久化；survivorship 需历史快照 | EXTEND |
| 5 | **ds_trading_calendar** | 时间完整性最高、provenance 最强、隔离度最高 | 静态小数据集，收益有限；适合验证第一个 by_date + PIT 契约 | EXTEND（ALREADY_HAVE 基础上） |

**最终选择不在本任务范围内。** 等待 DS-A1 approval + DS-A2 closure + ChatGPT review。

DS_L1_CANDIDATE_SHORTLIST = **PASS**

---

## 10. 严格边界执行

- 未修改任何 production 源码；未新增 provider；未联网探测；未新增依赖；未做 DB migration；未触碰真实用户 DB。
- 未触碰：PR #64 / #69 / #73/#75/#76/#77/#79、用户 AGENTS.md、AI与A股每日简报 automation。
- 未设计 DS-A1 contract；未执行 DS-A2；未实现 DS-L1；无 Phase 3 工作。
- 未修改 north-star 分支既有 whitespace。

---

## 11. 验收门

| Gate | 状态 |
|---|---|
| STABLE_HEAD_PINNED | PASS |
| CURRENT_VS_IN_PROGRESS_SEPARATED | PASS |
| PROVIDER_INGRESS_INVENTORIED | PASS |
| DATASET_MATRIX_COMPLETE_FOR_DISCOVERED_SCOPE | PASS |
| TEMPORAL_SEMANTICS_NOT_GUESSED | PASS |
| UNKNOWN_PRESERVED | PASS |
| STORAGE_CACHE_INVENTORIED | PASS |
| DATA_HEALTH_REUSE_MAP | PASS |
| FALLBACK_ROUTING_RECONCILIATION_MAP | PASS |
| DUPLICATION_HOTSPOTS_IDENTIFIED | PASS |
| DS_L1_REUSE_BOUNDARY | PASS |
| DS_L1_CANDIDATE_SHORTLIST | PASS |
| NO_NEW_DS_A1_CONTRACT | PASS |
| NO_PRODUCTION_CODE_CHANGE | PASS |
| NO_PROVIDER_INTEGRATION | PASS |
| REAL_USER_DB | NOT_TOUCHED |

---

## 最终状态

```
DS_R1 = READY_FOR_INDEPENDENT_REVIEW
BRANCH = docs/data-governance-existing-data-plane-inventory-v0.1
HEAD = <filled at commit>
PR = <filled at create>
EVIDENCE_STABLE_HEAD = 1be2ecba505a8108740c311c103a2c72d3bcd444
CHANGED_FILES = docs/data/EXISTING_DATA_PLANE_INVENTORY_V01.md, docs/data/EXISTING_DATA_PLANE_INVENTORY_V01.json
PR_READY = NO
MERGE = NO
```

STOP（不自动继续 DS-A2；DS-A2 启动门为 DS_A1_INDEPENDENT_REVIEW = APPROVE）。
