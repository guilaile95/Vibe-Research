# 数据健康中心 MVP 技术设计（草案 v2）

> 基线分支：`feature/research-system-v01`
> 基线提交：`cdd1a0fb589e4decb3b7196894fae9e1753ed0db`
> 设计分支：`design/data-health-center-mvp`

## 1. 目标与非目标

### 1.1 目标

数据健康中心是现有数据状态的只读解释层。MVP 回答五个问题：

1. 当前有哪些研究数据；
2. 数据质量是正常、部分可用还是不可用；
3. 数据来自什么时候，是否已经陈旧；
4. 是否使用缓存或降级结果；
5. 当前持仓建议是否被现有权威 gate 阻止，以及具体原因。

统一数据流如下：

```text
现有业务模块的权威结果/状态
        │
        ├─ 已有状态和时间元数据 ───────────────┐
        │                                      │
        └─ 真实调用路径写入最小健康事件 ──────┤
                                               ▼
                                         Health Adapter
                                               │
                                               ▼
                                      DataHealthRecord[]
                                               │
                                               ▼
                                      只读聚合 API / 前端
```

数据健康中心不成为新的业务数据源，不重新抓取外部数据，不重新计算业务结果，也不替代持仓建议 gate。

### 1.2 非目标

本 MVP 明确不做：

- 自动修复数据源；
- 自动重试全部模块；
- 新的全局 scheduler；
- 分钟级后台健康监控；
- 短信、邮件或站外提醒；
- Prometheus、Grafana 或外部监控平台；
- 新的持仓建议规则或投资政策；
- 模型供应商计费与可用性监控；
- 自动切换数据供应商；
- 完整全球交易日历；
- 健康历史趋势图和 SLA 报表；
- `POST /api/data-health/refresh`；
- P1 条件提醒。

## 2. 当前系统健康信号盘点

### 2.1 现状信号矩阵

下表只记录基线代码中已经存在的事实。`—` 表示当前代码没有该字段或权威元数据，不表示未来实现占位。

| source_id | 模块 | 代码位置 | 当前状态字段与枚举 | 当前数据时间字段 | 当前最近成功时间 | 当前缓存/降级标记 | 当前覆盖数量 | 错误摘要来源 | 是否影响持仓建议 | 当前前端位置 |
|---|---|---|---|---|---|---|---|---|---|---|
| `daily_review` | 每日复盘 | `backend/daily_review.py`、`backend/daily_review_cache.py`、`backend/app.py` | 顶层 `status` 与 `data_health.components.*`：`normal/partial/unavailable` | `generated_at`、`trade_date`、`data_cutoff`（当前恒为 `null`）；部分市场信封另有 `trade_date/data_time/fetched_at/is_stale` | 磁盘缓存外层 `saved_at`；内存仅保存写入时 monotonic 时间 | `cache_meta.source=memory/persisted/live/refresh`、`stale`、`refreshing`、`refresh_failed` | 8 个组件状态；广度含 `stock_count/valid_count/amount_valid_count` | `warnings` 与 `cache_meta.refresh_error`，经 `daily_review_errors.py` 清洗 | 是；广度不可用和复盘交易日缺失会阻断 | `/daily-review`，已显示总体/组件状态、交易日、生成时间和 stale 提示 |
| `portfolio_advice_gate` | 持仓建议 gate | `backend/portfolio_advice_service.py` | 无统一状态对象；通过 `PortfolioAdviceUnavailableError`、`PortfolioAdviceMarketDataError` 失败关闭 | 读取复盘 `trade_date`；没有 gate 自身时间 | — | — | 检查持仓非空、逐项有效价格、广度可用、复盘交易日存在 | `_EMPTY_HOLDINGS_MSG`、`_HOLDING_QUOTE_UNAVAILABLE_MSG`、`_MARKET_UNAVAILABLE_MSG`、`_REVIEW_TRADE_DATE_MSG` | 它本身就是唯一权威 gate | `/portfolio`；失败以请求错误展示，成功结果元数据也显示于 `/cockpit` |
| `portfolio_quotes` | 持仓行情覆盖 | `backend/portfolio.py` | 顶层 `data_status=normal/partial/unavailable`；单持仓 `data_status=normal/unavailable` | `updated` 是本次响应计算时间；`last_refresh` 是后台刷新点 | — | 行情失败时返回空 quote map；没有显式缓存命中标记 | `quote_coverage.valid_holdings/total_holdings/complete` | 当前仅由缺失价格体现，无稳定错误码 | 是；任一持仓无有效价格即阻断 | `/portfolio`，类型已包含 `data_status` 和 `quote_coverage`，页面主要展示建议错误而非独立健康摘要 |
| `quotes` | 个股行情 | `backend/app.py` 的 `/api/quote`、`backend/astock.py::tencent_quote` | HTTP 200/502；业务 body 没有统一状态枚举 | 行情项自带的源字段不构成统一权威时间；接口没有顶层时间 | — | `/api/quote` 无 TTL 缓存 | 请求代码数与返回项目可由当次响应计算，但未保留 | 502 detail 当前拼接边界异常 | 间接影响；持仓行情调用同一底层源 | `/stock-data`、`/watchlist`、`/portfolio` 等调用方 |
| `announcements` | 公告 | `backend/app.py` 的 `/api/announcements`、`backend/astock.py::announcements` | HTTP 200/502；无业务状态枚举 | 公告条目含来源日期；接口无顶层观测时间 | — | `_ANN_CACHE`，TTL 900 秒；响应不标识 cache hit | 返回条目数仅存在于当次响应 | 502 detail 当前为“公告源异常”加异常文本 | 不直接作为当前 gate 条件 | `/stock-data` 可选面板；板块动态数据也调用该源 |
| `financials` | 财务数据 | `backend/app.py` 的 `/api/financials`、`backend/astock.py::financials` | HTTP 200/501/502；无业务状态枚举 | 数据含报告期字段；接口无统一顶层时间 | — | `_FIN_CACHE`，TTL 1800 秒；响应不标识 cache hit | 当次响应字段完整性未统一计算 | 501 依赖缺失或 502“财务摘要异常” | 不直接作为当前 gate 条件 | `/stock-data` 财务面板 |
| `news_radar` | 资讯雷达 | `backend/newsradar.py`、`backend/app.py` | 无 `status`；有缓存即返回数据，无缓存返回 skeleton | `generated_at`、条目 `ts/time`、`recent_days` | `generated_at` 可视作最近完整抓取时间 | `radar.json` 磁盘缓存；skeleton 与真实空数据未用状态区分 | `stats.total_sources/failed_sources`、每赛道 `total/items` | `_fetch_source` 吞掉异常并累计 `failed_sources`；刷新边界返回 502 | 否 | `/intel` 显示来源数、时间和内容；没有 partial/unavailable 文字状态 |
| `sector_research` | 板块研究 | `backend/sector_research_data.py`、`backend/app.py`、`frontend/src/components/sectors/SectorResearchLiveData.tsx` | 动态数据 `status=normal/partial/unavailable`；面板 `status=ok/error`；研报发现另有 `error` | 动态数据 `fetched_at` UTC；研报有 `publish_date` | 仅存在于当次响应 | 研报发现元数据缓存 20 分钟，但动态数据无结果缓存；没有 cache hit 标记 | `ok_panels/fail_panels` 只在函数内，响应有公司和面板集合；发现接口有 `total_discovered/returned/truncated` | `warnings`、顶层 `error`、面板安全 `error` | 否 | `/sectors/:key/:tag` 的动态数据和研报发现面板 |
| `my_reports` | 我的研报/研报导入 | `backend/myreports.py`、`backend/app.py` | 无健康枚举；`ReportIndexCorruptedError` 表示索引损坏 | 每条 `imported_at` UTC、`publish_date` date-only | 最新 `imported_at` 可从索引只读聚合 | 无业务缓存；`index.json` 是权威索引 | `list_reports()` 条目数 | 稳定的 `ReportIndexCorruptedError.MESSAGE`；不存在索引时当前读取为空列表 | 否 | `/my-reports`；板块研报导入成功后跳转该页 |
| `watchlist_portfolio_storage` | 自选股/持仓存储 | `backend/watchlist_store.py`、`backend/portfolio.py` | 自选股 `valid/not_configured/corrupted`；持仓缺文件返回空数据，损坏抛 `PortfolioDataCorruptedError` | 自选股 `updated_at`；持仓 `last_refresh`，响应 `updated` 只是读取时刻 | 自选股 `updated_at`；持仓没有可靠的持久化成功时间字段 | 自选股前端 localStorage 仅草稿；持仓无业务缓存标记 | 自选代码数、持仓数 | 自选股 `corrupted`；持仓稳定损坏消息 | 是；无持仓直接阻断建议，存储损坏使流程不可用 | `/watchlist`、`/portfolio` |
| `evidence_ledger` | 投资逻辑与证据账本 | `backend/evidence_thesis_store.py`、`backend/evidence_thesis_service.py`、`backend/evidence_thesis_router.py` | 业务 thesis 状态 `active/weakened/invalidated/archived` 不是数据健康状态；存储异常有 `EvidenceLedgerCorruptedError`、`EvidenceLedgerSchemaVersionError` | `created_at/updated_at/accessed_at` 均规范到 UTC；`source_date` date-only | 可只读聚合最大 `updated_at` | SQLite WAL/backup 属于业务存储机制，不是健康缓存 | evidence/thesis 数量可只读查询 | 路由映射为稳定安全中文；底层 SQLite 文本不外泄 | 否 | `/thesis`、`/evidence` 与个股逻辑面板 |

### 2.2 已有状态枚举汇总

| 位置 | 当前枚举 | 语义 |
|---|---|---|
| 每日复盘及市场信封 | `normal/partial/unavailable` | 数据质量，可直接映射 |
| 持仓行情 | `normal/partial/unavailable` | 持仓价格覆盖质量，可直接映射 |
| 自选股 | `valid/not_configured/corrupted` | 配置/存储状态，需要 Adapter 映射 |
| 板块面板 | `ok/error` | 单面板调用结果，需要聚合映射 |
| 投资逻辑 | `active/weakened/invalidated/archived` | 业务对象生命周期，禁止映射为数据健康状态 |
| HTTP | `200/4xx/5xx` | 传输/请求结果，禁止直接等同数据质量 |

## 3. 现有语义冲突

以下问题均来自基线代码：

1. 每日复盘同时使用顶层 `status`、组件 `status`、市场信封 `is_stale` 和展示层 `cache_meta.stale`；同一页面需要跨层拼装健康含义。
2. `generated_at`、`updated`、`fetched_at`、`saved_at`、`last_refresh` 混用北京时间无时区字符串与 UTC ISO 8601，不能直接排序比较。
3. 每日复盘 `data_cutoff` 当前固定为 `null`，但页面仍以生成时间作为回退展示；生成时间不是业务数据截止时间。
4. 每日复盘磁盘缓存命中明确标记 stale，而公告、财务 TTL 缓存命中不对外标记，HTTP 200 容易被误解为实时数据。
5. 资讯雷达无缓存时返回与正式响应同形状的 skeleton；“尚未初始化”和“成功抓取但没有资讯”无法由状态字段区分。
6. 资讯雷达允许部分 RSS 失败并返回数据，但没有 `partial`；失败只体现在 `failed_sources`。
7. 自选股 `not_configured`、持仓缺文件返回空数据、研报索引不存在返回空列表，三者都表达首次启动，但语义和状态不同。
8. 持仓建议 gate 的阻断原因只在异常路径中即时产生，没有统一可查询的最后观察状态。
9. 持仓行情已有 `quote_coverage`，但页面主要展示生成建议时的失败，用户不能在请求建议前看到哪个权威前置条件未满足。
10. 个股行情、公告和财务成功/失败没有最近成功时间和稳定错误码；最近一次 502 也不能说明是否仍存在可用旧数据。
11. 板块动态数据拥有正确的 `normal/partial/unavailable`，但结果未持久化；健康中心若直接调用它就会形成重复抓取。
12. 我的研报和证据账本已有安全损坏异常，但没有只读健康摘要；若复用普通业务初始化入口，可能在健康 GET 中创建目录、数据库或表。
13. 前端多个页面分别解释状态，`partial` 的文字包括“部分缺失”“部分数据不可比较”“部分”，缺少统一入口。
14. 当前 gate 与前端按钮状态并非同一权威来源：例如决策舱仅按市场 status 禁用按钮，而持仓建议还检查持仓、行情覆盖和交易日。

## 4. 统一状态模型

### 4.1 质量与时效分离

MVP 对外质量状态固定为：

```text
normal
partial
unavailable
```

时效独立表达：

```text
is_stale: true | false
```

定义如下：

- `normal`：该来源当前可读取的权威结果满足该 Adapter 的完整性规则；
- `partial`：有可用结果，但存在关键字段缺失、部分来源失败或覆盖不足；
- `unavailable`：没有可用结果，或权威存储/最近真实调用明确失败；
- `is_stale=true`：质量判断成立，但按来源自己的 freshness 规则已经过期。

确定性优先级：

```text
1. 无有效结果且当前失败                         → unavailable
2. 有结果但关键字段或覆盖不足                   → partial
3. 结果满足完整性要求                           → normal
4. 在质量状态基础上独立计算 is_stale
5. 分别计算 is_cached 与 is_degraded
```

硬性语义：

- HTTP 200 不等于 `normal`；
- 存在缓存不等于 `normal`；
- 业务数据为空不等于 `unavailable`；
- 部分覆盖不等于 stale；
- stale 不等于 `unavailable`；
- `SOURCE_NOT_INITIALIZED` 表示尚无观察记录，不表示存储损坏；
- 业务对象状态（如 thesis `invalidated`）不参与健康状态映射。

### 4.2 Adapter 映射规则

| 当前信号 | 统一映射 |
|---|---|
| `normal` | `normal` |
| `partial` | `partial` |
| `unavailable` | `unavailable` |
| 自选股 `valid` | `normal` |
| 自选股 `not_configured` | `unavailable` + `SOURCE_NOT_INITIALIZED`，但不阻断建议 |
| 自选股 `corrupted` | `unavailable` + `SOURCE_CORRUPTED` |
| 板块全部面板 `ok` | `normal` |
| 板块部分 `ok`、部分 `error` | `partial` |
| 板块全部 `error` | `unavailable` |
| 首次启动且无权威文件/表/事件 | `unavailable` + `SOURCE_NOT_INITIALIZED` |
| 权威空集合且存储已初始化、结构有效 | `normal`，覆盖数为 0 |

## 5. DataHealthRecord 字段

统一只读对象：

```python
DataHealthStatus = Literal["normal", "partial", "unavailable"]

class DataHealthRecord(TypedDict):
    source_id: str
    module: str
    display_name: str

    status: DataHealthStatus
    is_stale: bool

    observed_at: str | None
    last_success_at: str | None
    data_trade_date: str | None
    data_cutoff: str | None

    stale_after_seconds: int | None
    is_cached: bool | None
    is_degraded: bool | None

    coverage_current: int | None
    coverage_expected: int | None

    last_error_code: str | None
    last_error_summary: str | None
    last_error_at: str | None

    blocks_advice: bool
    block_reason: str | None

    detail_path: str | None
```

字段规则：

- 所有 datetime 在 Adapter 边界转换为 UTC ISO 8601，例如 `2026-07-28T01:30:00Z`；
- `data_trade_date` 仅允许 `YYYY-MM-DD`；
- 不适用或当前代码没有可靠来源的字段为 `null`，不得伪造；
- `observed_at` 表示权威状态被业务路径观察或保存的时间，不等同于数据发生时间；
- `last_success_at` 表示最近一次真实业务调用成功或权威结果成功保存时间；
- `coverage_current/coverage_expected` 只从当前权威结果即时读取，不进入健康事件存储；
- `is_cached/is_degraded=true` 表示权威模块或当前有效事件能够明确证明；`false` 表示权威模块能够明确证明未使用；`null` 表示当前只读信息不足；
- `null` 不得被解释或展示成“实时数据”或“未降级”；
- `daily_review` 根据权威 `cache_meta` 给出 `is_cached=true/false`；`news_radar` 读取磁盘缓存时为 `true`；仅有四字段事件的 `announcements/financials` 无法证明 cache hit，必须为 `null`；
- 当前有效 `SOURCE_DEGRADED` 映射 `status=partial, is_degraded=true`；当前有效 `SOURCE_PARTIAL` 映射 `status=partial, is_degraded=false`；其他 normal/partial 来源没有权威降级证据时为 `null`，只有权威模块明确未降级才为 `false`；
- `last_error_summary` 仅由稳定 `error_code` 映射，不接收原始异常文本；
- `blocks_advice` 与 `block_reason` 只映射现有 gate 最近一次真实评估，不使用 `overall_status` 推导。

## 6. stale 计算规则

### 6.1 通用算法

每个 Adapter 声明：

```text
freshness_basis
stale_after_seconds
calendar_type
```

计算顺序：

1. 从声明的 `freshness_basis` 按顺序选择第一个有效时间；
2. 将时间转换为 UTC；
3. 若来源是不随市场日历变化的用户存储，`stale_after_seconds=null` 且 `is_stale=false`；
4. 若来源是连续时间数据，比较 `now_utc - basis_time > stale_after_seconds`；
5. 若来源是交易日数据，先计算“当前期望交易日”，再比较 `data_trade_date`；
6. 权威模块已有 stale 结论时优先采用，例如每日复盘 `cache_meta.stale=true`；
7. 无任何时间依据时不伪造 stale：`is_stale=false`，同时以 `SOURCE_NOT_INITIALIZED` 或 `SOURCE_PARTIAL` 表达质量缺口。

### 6.2 首批来源规则

| source_id | freshness_basis（优先顺序） | 建议阈值 | calendar_type | 说明 |
|---|---|---:|---|---|
| `daily_review` | `cache_meta.stale` → `data_trade_date` → `saved_at/generated_at` | 交易日规则；时间回退 36 小时 | `CN_MARKET_CONSERVATIVE` | 不修改现有 300 秒内存 TTL；展示缓存 stale 继续权威 |
| `portfolio_advice_gate` | `observed_at=max(last_success_at,last_error_at)` | 300 秒 | `CONTINUOUS` | 超过 300 秒，或持仓文件、`portfolio_quotes`、`daily_review` 任一观察时间更新时 stale；stale 不改变最近 gate 结论 |
| `portfolio_quotes` | 最小事件 `last_success_at/last_error_at` | 300 秒（交易时段） | `CN_MARKET_CONSERVATIVE` | 非交易时段延续最近收盘观察，下一交易时段开始后重新计时 |
| `quotes` | 最小事件 `last_success_at/last_error_at` | 300 秒（交易时段） | `CN_MARKET_CONSERVATIVE` | 只记录真实行情调用，不主动探测 |
| `announcements` | 最小事件 `last_success_at/last_error_at` | 86400 秒 | `CONTINUOUS` | 不把 15 分钟业务 TTL 当作公告业务日期 |
| `financials` | 最小事件 `last_success_at/last_error_at` | 604800 秒 | `REPORTING_PERIOD` | 当前事件没有报告期，MVP 以最近真实成功观察时间保守判断 |
| `news_radar` | 缓存 `generated_at` | 86400 秒 | `CONTINUOUS` | `failed_sources>0` 决定 partial，不等同 stale |
| `sector_research` | 最小事件 `last_success_at/last_error_at` | 86400 秒 | `CONTINUOUS` | 动态面板当次 partial 记录 `SOURCE_PARTIAL` |
| `my_reports` | 最新 `imported_at` | `null` | `USER_MANAGED` | 用户档案没有自动过期；索引损坏仍为 unavailable |
| `watchlist_portfolio_storage` | 自选股 `updated_at`、文件 mtime | `null` | `USER_MANAGED` | 用户配置不因时间变旧 |
| `evidence_ledger` | 最大 `updated_at` | `null` | `USER_MANAGED` | 账本内容不因时间自动判坏 |

### 6.3 A 股保守交易日规则

MVP 不建设交易日历服务，优先复用现有北京时间逻辑。`CN_MARKET_CONSERVATIVE` 规则固定如下：

1. 使用 `Asia/Shanghai` 解释盘前、盘中、盘后；
2. 周六、周日不要求生成新的交易日数据，最近周五结果不因自然日跨越立即 stale；
3. 工作日 09:30 前，期望交易日仍为最近一个工作日；
4. 工作日 09:30–15:00，分钟级行情按连续阈值判断；日级复盘允许使用上一交易日，直到当日收盘后刷新窗口；
5. 工作日 15:30 后，日级来源期望 `data_trade_date` 为当天；15:00–15:30 是数据落地宽限期；
6. 没有节假日日历时，不把工作日无交易直接判定为损坏：超过阈值标记 stale，并在详情中显示“未接入交易日历，采用保守工作日规则”；
7. 跨市场数据不得套用 A 股规则；没有相应市场日历时仅按带时区的 `observed_at/last_success_at` 判断，并标明保守规则。

## 7. Adapter 设计

### 7.1 模块边界

实现阶段新增：

```text
backend/data_health_router.py       # FastAPI 只读路由、筛选参数与 404/422
backend/data_health_service.py      # DataHealthRecord、聚合、总体状态、错误码映射
backend/data_health_adapters.py     # 11 个只读 Adapter 与注册表
backend/data_health_event_store.py  # 独立极小 JSON 元数据存储；读路径绝不创建
```

`backend/app.py` 只增加 router import/include，不拆分、不重构现有路由。真实数据源成功/失败路径以最小调用方式记录事件；记录器只接收 `source_id`、结果类别和稳定错误码，不接收业务响应或异常对象。

Adapter 统一协议：

```python
class DataHealthAdapter(Protocol):
    source_id: str
    module: str

    def read(self, context: HealthReadContext) -> DataHealthRecord:
        """严格只读；不得联网、写文件、初始化 schema 或触发业务刷新。"""
```

`HealthReadContext` 只包含 `now_utc`、数据目录解析结果和时区/日历辅助函数，不包含外部客户端。

### 7.2 只读保证

每个 Adapter 必须满足：

- 不调用 `daily_review.generate_daily_review()`；
- 不调用 `portfolio.get_portfolio()`；
- 不调用 `newsradar.fetch_radar()`；
- 不调用 `sector_research_data.get_sector_dynamic_data()`；
- 不调用 `astock`、`market` 或任何网络函数；
- 不调用会执行 `CREATE TABLE`、迁移、备份或 `os.makedirs` 的业务初始化函数；
- SQLite 统一以 `mode=ro` 打开；
- JSON 文件只使用读取模式；
- 缺文件、缺表或缺来源事件返回 `SOURCE_NOT_INITIALIZED`；
- 损坏只返回稳定错误码，不删除、不修复、不覆盖原文件。

### 7.3 最小健康事件存储

代码调查证明 `quotes`、`announcements`、`financials`、`portfolio_quotes`、`portfolio_advice_gate` 和 `sector_research` 没有可供只读聚合的最近运行元数据，因此采用批准的极小独立存储：

```text
路径：VR_DATA_DIR/data_health_events.json
默认：~/.vibe-research/data_health_events.json
schema：data-health-events.v1
```

单条记录严格只有：

```json
{
  "source_id": "quotes",
  "last_success_at": "2026-07-28T01:30:00Z",
  "last_error_at": null,
  "last_error_code": null
}
```

顶层仅允许 `schema_version` 与以 `source_id` 为键的 `events`。禁止持久化：

- 原始异常及其字符串；
- 中文错误摘要；
- traceback、路径、URL、请求参数、header、API key；
- 股票代码、行情、公告、财务字段；
- 覆盖数量或失败明细；
- 缓存内容、业务响应或历史趋势。

写入约束：

1. 只有现有业务真实调用路径完成后才能记录；
2. 成功更新 `last_success_at`，保留历史 `last_error_at/last_error_code`；完整成功是否恢复 normal 由时间比较决定；
3. 明确部分成功同时更新 `last_success_at`、`last_error_at` 和 `last_error_code=SOURCE_PARTIAL`；明确降级成功同理记录 `SOURCE_DEGRADED`；相同时间戳时部分/降级事件优先；
4. hard failure 只更新 `last_error_at/last_error_code`，保留以前的 `last_success_at`；
5. 文件不存在时允许创建 `data-health-events.v1`；文件存在时必须先完整读取并严格校验；
6. JSON 损坏、schema 高于支持版本、顶层或记录含额外字段、未知 `source_id` 时拒绝写入；不得把损坏文件当成空集合；
7. `SOURCE_NOT_INITIALIZED` 仅由 Adapter 在缺记录时合成，所有来源的事件写入器均拒绝持久化该值；
8. 拒绝写入时不得删除、重命名、覆盖、恢复或静默清洗原文件，原内容、size 和 mtime 必须保持不变；
9. 使用单 Python 进程内线程锁、临时文件、`fsync` 和 `os.replace` 原子写入；MVP 仅支持单应用实例/单 Python 进程，不宣称跨进程锁或多 worker 写安全；
10. 并发更新不同 `source_id` 必须在同一线程锁内完成 read-validate-modify-write，不丢失已提交事件；
11. 事件写入失败不得改变原业务接口的成功或失败语义；只写安全日志中的异常类型；
12. 健康 GET 只调用 `load_events_readonly()`；文件不存在直接返回空事件集合，不创建目录或文件；
13. 独立存储不复用 `daily_reviews.sqlite3`、`evidence_thesis.db` 或其他业务数据库。

#### 每个来源的 observation_time 严格单调

写入器不得依赖墙上时钟自然递增。每次写入先解析该 `source_id` 的现有时间：

```python
existing_max = max(last_success_at, last_error_at)
candidate = now_utc

if candidate <= existing_max:
    observation_time = existing_max + timedelta(microseconds=1)
else:
    observation_time = candidate
```

规则固定为：

- 同一次 partial、degraded 或 gate-block 写入的 `last_success_at/last_error_at` 使用同一个 `observation_time`；
- 后续完整成功必须使用严格更晚的时间，因此冻结时间测试也能从 partial/degraded/block 恢复；
- 不增加第五个持久化字段；
- 时间单调性按 `source_id` 独立维护，不要求不同来源之间排序；
- 并发调用在线程锁内串行完成读取、单调时间计算和原子替换，保证同一来源每次已提交观察时间严格递增。

## 8. 首批数据源清单

首批 Adapter 固定为 11 个，不在实现阶段扩容。

### 8.1 按请求来源的观察范围

`quotes`、`announcements`、`financials`、`sector_research` 统一表示“最近一次任意真实业务调用的来源级观察状态”。该语义不按股票代码、板块标识或请求对象细分：

- 不代表所有股票、所有板块或所有请求对象均正常；
- 不持久化股票代码、板块标识、请求参数或覆盖明细；
- 这四个事件型 Adapter 的 `coverage_current/coverage_expected` 默认为 `null`；
- `/data-health` 卡片固定显示“最近一次真实调用”；
- 详情固定显示：“该状态来自此数据源最近一次真实业务调用，不代表全部股票或板块均已验证。”

`portfolio_quotes` 是持仓场景专用来源，表示最近一次持仓行情覆盖观察；它与通用 `quotes` 分开记录、分开展示，不互相覆盖或推导。

### 8.2 Adapter 明细

| source_id | 权威模块/读取函数 | 只读行为 | 缺文件/记录 | 损坏 | 无数据 | partial 判定 | stale 判定 | 建议字段规则 |
|---|---|---|---|---|---|---|---|---|
| `daily_review` | `daily_review._cached_review()` 与 `daily_review_cache.load_latest_review()`；不得调用 generate | 先读有效内存结果，再读最近成功磁盘缓存 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED`；Adapter 需区分文件存在但 loader 拒绝 | 已初始化的合法空组件按现有 status | 直接使用权威顶层 status | `cache_meta` 同义规则；磁盘结果 stale；交易日回退规则 | 固定 `blocks_advice=false, block_reason=null`；详情说明它是 preflight 输入 |
| `portfolio_advice_gate` | `portfolio_advice_service` 现有 preflight 的最后真实事件；同时读取依赖观察时间 | 不调用 prepare/generate；读取最近真实 gate 评估 | `unavailable/SOURCE_NOT_INITIALIZED`，`blocks_advice=false`，页面显示尚未评估 | 事件文件损坏时 status unavailable，但不伪造业务阻断 | `NO_HOLDINGS` 是成功完成的业务评估 | gate 运行健康不产生 partial；业务允许或阻断均为 normal | 300 秒，或持仓文件、portfolio quotes、daily review 更新 | 唯一可输出建议字段；四项稳定业务码映射最近 gate 结论 |
| `portfolio_quotes` | `portfolio.get_portfolio()` 真实调用完成时记录事件；Adapter 只读事件 | 不重新取行情 | `unavailable/SOURCE_NOT_INITIALIZED` | 事件文件损坏安全失败 | 无持仓时权威 `data_status=normal`，但 gate 另行评估 | 当次 `data_status=partial` 记录 `SOURCE_PARTIAL` | 交易时段 300 秒 | 固定 `false/null`；详情说明它是 preflight 输入 |
| `quotes` | `astock.tencent_quote()` 真实调用边界记录事件；Adapter 只读事件 | 不构造股票池，不调用行情源 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 当次请求空响应由业务路径记录 `SOURCE_UNAVAILABLE` | 返回部分请求代码时记录 `SOURCE_PARTIAL`，覆盖数不持久化 | 交易时段 300 秒 | 固定 `false/null` |
| `announcements` | `astock.announcements()` 真实调用边界记录事件 | 不读取 `_ANN_CACHE` 私有内容，不联网 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 合法空列表是 normal | 业务路径明确部分结果时才记录 `SOURCE_PARTIAL` | 86400 秒 | 固定 `false/null` |
| `financials` | `astock.financials()` 真实调用边界记录事件 | 不读取 `_FIN_CACHE` 私有内容，不联网 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 结构有效但无已披露指标为 partial，不假装 unavailable | 关键财务字段缺失时记录 `SOURCE_PARTIAL` | 604800 秒 | 固定 `false/null` |
| `news_radar` | 只读 `newsradar.CACHE_FILE`；解析现有 `generated_at/stats` | 不调用 `get_radar()`，避免 skeleton 混淆；不刷新 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 成功缓存且 items 为 0 仍可 normal | `failed_sources>0` 且小于 total；全部失败 unavailable | 86400 秒 | 固定 `false/null` |
| `sector_research` | `get_sector_dynamic_data()` 真实调用完成后记录聚合事件；Adapter 只读事件 | 不调用板块动态数据和研报发现 | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 注册板块暂无结果不是损坏 | 当次 status=partial 记录 `SOURCE_PARTIAL` | 86400 秒 | 固定 `false/null` |
| `my_reports` | `myreports._load_index_normalized()` 的只读等价入口；实现时新增公开只读摘要函数，禁止迁移/回写 | 文件存在时只读校验索引，聚合 count/max(imported_at) | `unavailable/SOURCE_NOT_INITIALIZED` | `unavailable/SOURCE_CORRUPTED` | 合法空索引 normal，coverage 0/0 | 索引合法但部分文件缺失为 partial | 不自动 stale | 固定 `false/null` |
| `watchlist_portfolio_storage` | `watchlist_store.get_watchlist_status()`；持仓使用只读结构校验，不调用带行情的 getter | 读取 JSON，不刷新、不迁移、不写备份 | 两者均未配置：`unavailable/SOURCE_NOT_INITIALIZED`；其中一个有效则 partial | 任一权威文件损坏且另一个有效为 partial；两者均不可读为 unavailable | 已初始化的空自选/空持仓 normal；gate 另行解释无持仓 | 两个子存储一好一坏/未配置 | 不自动 stale | 固定 `false/null`；详情说明持仓是 preflight 输入 |
| `evidence_ledger` | `evidence_thesis_store.read_transaction()` 或等价 `mode=ro` 摘要查询 | 只读 schema version、integrity、evidence/thesis count 和最大 updated_at | `unavailable/SOURCE_NOT_INITIALIZED`；不得初始化 DB | `SOURCE_CORRUPTED` 或 `SOURCE_SCHEMA_INCOMPATIBLE` | 已初始化空库 normal，coverage 0/0 | schema 可读但单项计数查询失败不降级吞错，整体 unavailable | 不自动 stale | 固定 `false/null` |

## 9. 持久化决策

最终选择是混合方案，不保留实现期二选一：

- 有权威状态的 `daily_review`、`news_radar`、`my_reports`、`watchlist_portfolio_storage`、`evidence_ledger` 按请求直接只读；
- 缺少权威运行元数据的 `portfolio_advice_gate`、`portfolio_quotes`、`quotes`、`announcements`、`financials`、`sector_research` 记录独立最小健康事件；
- 不新增数据健康数据库；使用独立、原子写入的极小 JSON 元数据文件；
- 不复制业务结果，不保存覆盖明细，不建设第二套业务缓存；
- 事件没有历史数组，只保留每个 `source_id` 的最近成功和最近错误；因此本 MVP 不支持趋势图。

采用最小事件存储的必要性已由代码调查证明：这些模块的 HTTP 状态和当次响应结束后没有可只读复用的最近成功/错误元数据；纯 Adapter 会永久把它们显示为未初始化，主动探测则违反禁止重复抓取的边界。

## 10. 聚合算法

### 10.1 单来源事件归一化

下列通用状态机适用于 `portfolio_quotes/quotes/announcements/financials/sector_research`。`portfolio_advice_gate` 的 error code 表示业务结论而非运行错误，必须使用第 13 节的专用映射：成功完成评估的允许与阻断均为 status normal。

```text
无记录
  → unavailable + SOURCE_NOT_INITIALIZED

存在 last_error_at，且不存在 last_success_at
  → hard error: unavailable
  → SOURCE_PARTIAL / SOURCE_DEGRADED: unavailable
    （没有可用成功结果，不能称为部分可用）

last_success_at > last_error_at
  → normal
  → 保留历史 last_error_code/last_error_at 供详情展示，
    但旧错误不决定当前质量状态

last_error_at >= last_success_at
且 last_error_code == SOURCE_PARTIAL
  → partial
  → is_degraded = false

last_error_at >= last_success_at
且 last_error_code == SOURCE_DEGRADED
  → partial
  → is_degraded = true

last_error_at >= last_success_at
且为其他错误码
  → unavailable
```

两个时间字符串必须先解析为带时区 UTC datetime，再比较；无效时间 fail-closed 为 `unavailable + SOURCE_CORRUPTED`，不得按字符串静默排序。相同时间戳时最后写入的 `SOURCE_PARTIAL/SOURCE_DEGRADED` 优先。`observed_at=max(last_success_at,last_error_at)`。完整成功可以保留历史错误，但只要成功时间更新得更晚，当前质量就恢复 normal。

状态转移表：

| 转移 | 事件结果 | 当前状态 |
|---|---|---|
| 未初始化 → 成功 | 仅 `last_success_at` | normal |
| 未初始化 → 失败 | 仅 `last_error_at` | unavailable；partial/degraded 也因无成功结果而 unavailable |
| 成功 → partial | 同时写成功与 `SOURCE_PARTIAL` 错误时间 | partial，`is_degraded=false` |
| partial → 完整成功 | 更新为更晚 `last_success_at`，保留历史错误 | normal |
| 成功 → degraded | 同时写成功与 `SOURCE_DEGRADED` 错误时间 | partial，`is_degraded=true` |
| degraded → 完整成功 | 更新为更晚 `last_success_at`，保留历史错误 | normal |
| 成功 → hard failure | 更新更晚 `last_error_at` | unavailable |
| hard failure → 完整成功 | 更新更晚 `last_success_at`，保留历史错误 | normal |

`is_stale` 在上述结果之后独立计算。事件文件整体损坏时，依赖该文件的来源分别返回 `SOURCE_CORRUPTED`；已有权威文件 Adapter 不受影响。

### 10.2 总体状态

先区分：

```text
initialized_items：last_error_code != SOURCE_NOT_INITIALIZED
not_initialized_items：last_error_code == SOURCE_NOT_INITIALIZED
```

聚合顺序固定为：

```python
initialized = [
    item for item in items
    if item.last_error_code != "SOURCE_NOT_INITIALIZED"
]

if not initialized:
    overall_status = "unavailable"
elif all(item.status == "unavailable" for item in initialized):
    overall_status = "unavailable"
elif any(
    item.status in {"partial", "unavailable"} or item.is_stale
    for item in initialized
):
    overall_status = "partial"
else:
    overall_status = "normal"
```

未使用的可选来源不会永久拖低 overall status；11 个来源全部未初始化时为 unavailable；存在已初始化来源但它们全部 unavailable 时仍为 unavailable。`portfolio_advice_gate` 的允许或阻断不参与 overall status 计算。

全局 `blocks_advice` 不是从 `overall_status` 推导，并且只能来自 `portfolio_advice_gate`：

```text
最近一次现有 portfolio advice gate 明确阻断 → true
最近一次现有 gate 明确放行           → false
尚未运行 gate                         → false，并显示“尚未评估”
```

其余十个 Adapter 必须固定 `blocks_advice=false, block_reason=null`。`block_reasons` 也只能包含最近一次 `portfolio_advice_gate` 的稳定业务结论。这意味着 `overall_status=partial` 时可能仍允许建议，`overall_status=normal` 也不用于替代下一次建议请求中的实时 gate 检查。

## 11. API 设计

### 11.1 `GET /api/data-health`

查询参数：

| 参数 | 类型 | 允许值 |
|---|---|---|
| `module` | 单个 string | 精确匹配一个已注册 module；MVP 不支持重复参数、逗号分隔或多 module 筛选 |
| `status` | string | `normal/partial/unavailable` |
| `is_stale` | bool | `true/false` |
| `blocks_advice` | bool | `true/false` |

未知 `module`、重复 `module`、逗号分隔 module、多 module 请求或非法枚举/布尔值均返回 422。筛选只影响 `items`；`summary` 仍统计完整 11 个来源，顶层 `overall_status`、`blocks_advice` 和 `block_reasons` 也始终基于完整 11 个来源，防止筛选改变全局结论。

响应：

```json
{
  "data": {
    "overall_status": "partial",
    "blocks_advice": true,
    "block_reasons": [
      {
        "source_id": "portfolio_advice_gate",
        "error_code": "HOLDING_QUOTES_UNAVAILABLE",
        "summary": "部分持仓缺少有效行情，当前无法生成可靠的持仓建议。"
      }
    ],
    "summary": {
      "normal": 5,
      "partial": 2,
      "unavailable": 4,
      "stale": 3,
      "not_initialized": 2
    },
    "items": []
  }
}
```

列表稳定按 Adapter 注册顺序返回，不按健康状态动态排序，避免页面跳动；前端异常区自行筛选。

`summary` 的质量状态满足：

```text
normal + partial + unavailable = 11
```

`stale` 与 `not_initialized` 是正交/子集统计，不是第四、第五种质量状态：

```text
not_initialized 是 unavailable 的子集
stale 可与 normal / partial / unavailable 任一状态重叠
```

因此示例中的 summary 数字全部相加可能超过 11，前端不得把它们绘制成互斥分区。

### 11.2 `GET /api/data-health/{source_id}`

已注册来源返回：

```json
{
  "data": {
    "record": {},
    "calculation": {
      "quality_basis": ["daily_review.status", "daily_review.data_health.components"],
      "freshness_basis": "data_trade_date",
      "calendar_type": "CN_MARKET_CONSERVATIVE",
      "rule_summary": "展示缓存 stale 优先；否则按交易日和 36 小时回退规则判断。"
    },
    "related_pages": [
      {"label": "查看每日复盘", "path": "/daily-review"}
    ]
  }
}
```

未知 `source_id` 返回 404。异常边界固定为：

```text
单个 Adapter 的可预期读取失败
  → 该来源返回 unavailable + 稳定安全错误码
  → 不影响其余来源

Adapter 注册表、响应序列化或聚合框架自身异常
  → HTTP 500
  → {"detail": "数据健康服务暂不可用"}
```

编程错误不得伪装成 `SOURCE_UNAVAILABLE`。任何路径都不得返回 traceback、绝对路径或 SQLite 原始文本。

### 11.3 明确不提供 Refresh API

MVP 不提供 `POST /api/data-health/refresh`。数据刷新继续使用已有业务入口，例如每日复盘刷新、资讯雷达刷新和用户主动加载个股数据。健康中心仅展示既有状态。

## 12. 前端设计

### 12.1 路由与导航

- 新增页面路由：`/data-health`；
- 主导航名称：`数据健康`；
- 在 `frontend/src/router.tsx` 懒加载；
- 在 `frontend/src/components/layout/Layout.tsx` 的 `NAV` 增加入口；
- 页面实现建议位于 `frontend/src/pages/DataHealth.tsx`；
- API 类型和调用分别进入 `frontend/src/lib/api/types.ts` 与 `frontend/src/lib/api.ts`，不在页面重复定义。

### 12.2 页面信息结构

页面按以下顺序展示：

1. **全局概览**：总体状态、正常/部分/不可用/stale 数量；
2. **建议可用性**：明确显示“允许生成 / 当前阻止 / 尚未评估”，列出现有 gate 原因；
3. **异常和陈旧来源**：只列 partial、unavailable 或 stale；
4. **全部数据源**：11 个来源卡片；
5. **单个来源详情**：点击卡片后请求详情 API，在页面侧栏或下方详情区展示计算依据和相关入口，不增加第三个 API。

每张卡片同时显示文字和视觉标识：

- `正常`、`部分可用`、`不可用`；
- `数据陈旧`；
- `缓存结果`；
- `降级结果`；
- 数据交易日或截止时间；
- 最近成功时间；
- 覆盖数量（存在时显示 `current / expected`，未知显示“未提供”）；
- 安全错误摘要；
- 是否阻止持仓建议；
- `查看详情` 与业务页面入口。

禁止只用红黄绿表达状态。状态 icon 必须带可见文字并设置可读的 `aria-label`。

### 12.3 首批页面级轻量入口

实现阶段只接入两个现有页面：

1. `/daily-review`：在当前交易日/生成时间区域增加“数据截至… / 是否缓存或 stale / 查看数据健康详情”；
2. `/portfolio`：在持仓建议区域上方增加“建议可用性 / 最近 gate 原因 / 查看数据健康详情”。

不批量修改其余页面，不删除或重排现有数据展示。

### 12.4 前端状态

- 首次加载显示 skeleton，不用“正常”占位；
- API 加载失败显示“数据健康服务暂不可用”，不覆盖上一次成功页面数据；
- 11 个来源均未初始化时显示引导文字，但仍展示每个来源的 `SOURCE_NOT_INITIALIZED`；
- `is_cached/is_degraded=true` 显示对应标签，`false` 不显示，`null` 只在详情显示“当前来源未提供该信息”；不得把 `null` 展示为“实时数据”或“未降级”；
- 建议区同时显示“最近一次评估结果”“该评估是否已经陈旧”“下一次生成仍会重新执行实时 preflight”；gate stale 只标记评估时效，不改写最近允许/阻断结论；
- 筛选在 URL query 中持久化，非法 query 由前端清理为默认值，API 仍保持 422 契约；
- 页面没有刷新数据源按钮；仅可重新读取健康 API。

## 13. 持仓建议 gate 关系

唯一权威关系：

```text
portfolio.get_portfolio() 的持仓与行情覆盖
                  │
daily_review.generate_daily_review() 的 breadth/trade_date
                  │
                  ▼
portfolio_advice_service 现有 preflight gate
  ├─ 无持仓
  ├─ 任一持仓无有效价格
  ├─ 市场广度 unavailable
  └─ 复盘 trade_date 缺失
                  │
          记录最小 gate 事件
                  │
                  ▼
portfolio_advice_gate Adapter
                  │
                  ▼
运行健康 status + 业务结论 blocks_advice / block_reason（只读展示）
```

实现约束：

- 将现有四项 gate 结果映射为稳定错误码，但不修改判断条件或异常类型；
- gate 成功完成 preflight 评估时，无论业务结论是允许还是阻断，`status=normal`；`NO_HOLDINGS` 是有效业务评估结果，因此为 `status=normal, blocks_advice=true`；
- 尚未评估时为 `status=unavailable, last_error_code=SOURCE_NOT_INITIALIZED, blocks_advice=false`，页面显示“尚未评估”；
- gate 业务阻断码可复用事件记录的 `last_error_code`，但这些代码表示最近业务结论，不代表事件存储损坏；
- 只有实际持仓建议 preflight 执行时记录 gate 事件；
- 健康中心不得为了更新 gate 状态调用 preflight；
- 只有 `portfolio_advice_gate` 可以输出 `blocks_advice/block_reason`；其他十个 Adapter 即使自身 unavailable/partial 也固定为 `false/null`，仅在详情说明“该来源是 preflight 输入之一，最终是否阻断以最近一次 gate 评估为准”；
- gate `is_stale=true` 当且仅当当前时间超过 `observed_at` 300 秒、持仓文件 mtime、`portfolio_quotes.observed_at` 或 `daily_review.observed_at` 中任一晚于 gate `observed_at`；
- gate stale 不自动改变 `blocks_advice/block_reason`；
- 模型供应商、模型输出和结果持久化错误不属于市场数据 gate，不映射为 `blocks_advice`；
- `overall_status != normal` 不能作为新 gate；
- 每次实际生成建议仍执行原有实时 gate，健康页面最后状态不提供放行保证。

### 13.1 Gate 事件专用编码

`portfolio_advice_gate` 不使用第 10.1 节的通用错误状态机；它必须同时表达“preflight 是否成功运行”和“成功运行后的业务结论”。`SOURCE_NOT_INITIALIZED` 是 Adapter 在缺记录时合成的值，不得写入事件文件。

| 情形 | 事件文件写入 | Gate Adapter 映射 |
|---|---|---|
| 尚未评估 | 无事件记录 | `status=unavailable`、`last_error_code=SOURCE_NOT_INITIALIZED`、`blocks_advice=false`、`block_reason=null` |
| 评估允许 | `last_success_at=observation_time`；保留历史 `last_error_at/last_error_code` | `last_success_at > last_error_at` → `status=normal`、`blocks_advice=false`、`block_reason=null` |
| 评估明确阻断 | 同一次成功 preflight 写入 `last_success_at=last_error_at=observation_time`，`last_error_code=<gate business code>` | 两个时间相等且 code 属于四项业务码 → `status=normal`、`blocks_advice=true`、`block_reason=稳定安全摘要` |
| Gate 运行失败 | 只写 `last_error_at=observation_time` 和 `SOURCE_TIMEOUT/SOURCE_UNAVAILABLE`，不更新 `last_success_at` | `last_error_at >= last_success_at` 且不是业务码 → `status=unavailable`、`blocks_advice=false`；页面显示最近 Gate 运行失败，不伪造允许或阻断 |

Gate business code 固定为：

```text
NO_HOLDINGS
HOLDING_QUOTES_UNAVAILABLE
MARKET_BREADTH_UNAVAILABLE
REVIEW_TRADE_DATE_UNAVAILABLE
```

Gate 事件恢复流程：

| 转移 | 写入 | 结果 |
|---|---|---|
| 阻断 → 允许 | 使用严格更晚 `observation_time` 更新 `last_success_at`，保留旧业务码 | `status=normal, blocks_advice=false` |
| 允许 → 阻断 | 使用同一新时间写成功时间、错误时间和业务码 | `status=normal, blocks_advice=true` |
| 运行失败 → 允许 | 使用严格更晚时间更新 `last_success_at` | `status=normal, blocks_advice=false` |
| 运行失败 → 阻断 | 使用同一严格更晚时间更新成功时间、错误时间和业务码 | `status=normal, blocks_advice=true` |

上述恢复依赖第 7.3 节的按来源单调时间：即使测试冻结 `now_utc`，新观察时间也严格晚于现有最大时间。

## 14. 安全错误模型

### 14.1 稳定错误码

| error_code | 安全中文摘要 | 适用场景 |
|---|---|---|
| `SOURCE_NOT_INITIALIZED` | 尚无该数据源的成功运行记录。 | 缺文件、缺表、缺事件或首次启动 |
| `SOURCE_STALE` | 数据仍可读取，但已超过该来源的时效规则。 | 仅详情/标签；不覆盖质量状态 |
| `SOURCE_PARTIAL` | 数据源仅返回部分可用结果。 | 部分覆盖或部分上游失败 |
| `SOURCE_UNAVAILABLE` | 数据源当前不可用，且没有可用结果。 | 稳定通用失败 |
| `SOURCE_CORRUPTED` | 数据存储无法安全读取，请检查备份或恢复流程。 | JSON/SQLite 损坏 |
| `SOURCE_SCHEMA_INCOMPATIBLE` | 数据存储版本与当前程序不兼容。 | 账本 schema 版本不匹配 |
| `SOURCE_TIMEOUT` | 数据源请求超时。 | 真实业务调用超时事件 |
| `SOURCE_DEGRADED` | 当前使用降级结果，部分能力不可用。 | 权威模块明确降级 |
| `NO_HOLDINGS` | 当前没有持仓，无法生成持仓建议。 | 现有 gate |
| `HOLDING_QUOTES_UNAVAILABLE` | 部分持仓缺少有效行情，当前无法生成可靠的持仓建议。 | 现有 gate |
| `MARKET_BREADTH_UNAVAILABLE` | 市场广度不可用，当前无法生成可靠的持仓建议。 | 现有 gate |
| `REVIEW_TRADE_DATE_UNAVAILABLE` | 每日复盘缺少交易日，当前无法生成可靠的持仓建议。 | 现有 gate |

中文摘要只由服务层的静态映射表生成。事件存储永远不写摘要。

### 14.2 禁止外泄

API、事件文件和前端禁止出现：

- 绝对文件路径；
- SQLite 原始错误；
- 完整上游响应；
- Authorization header、API key；
- Python traceback；
- 命令行参数；
- 用户持仓明细、股票代码集合；
- 原始异常字符串和第三方 URL 查询参数。

内部记录日志时仅允许 `source_id`、稳定 `error_code` 和异常类型名；不得记录异常全文。

## 15. 测试设计

### 15.1 后端单元测试

新增建议文件：

```text
backend/tests/test_data_health_service.py
backend/tests/test_data_health_adapters.py
backend/tests/test_data_health_event_store.py
backend/tests/test_data_health_api.py
```

覆盖：

1. 三状态映射与未知状态失败关闭；
2. stale 与质量状态正交：normal+stale、partial+fresh、partial+stale；
3. 每个来源的 freshness basis 和阈值；
4. 周末、工作日盘前、盘中、盘后和无交易日历的保守规则；
5. UTC、北京时间无时区旧字段、跨时区 ISO datetime 归一化；
6. 缓存和降级标记互不推导；
7. 覆盖率 `0/0`、部分覆盖和未知覆盖；
8. error_code 到安全中文映射；
9. 原始路径、traceback、Authorization、API key 和 SQLite 文本不会进入响应；
10. 现有 gate 四项结果到 `blocks_advice/block_reason` 的一一映射；
11. 总体状态聚合全部分支；
12. 空系统首次启动 11 个来源均返回稳定记录；
13. 缺文件读取前后目录树完全一致；
14. 损坏 JSON、损坏事件文件、损坏 SQLite、schema 不兼容；
15. 合法空自选、空持仓、空研报索引和空账本不是损坏；
16. 事件成功、部分、失败的原子更新；
17. 事件写失败不影响原业务结果；
18. 事件 schema 拒绝额外字段，证明没有业务数据落盘。
19. partial 后完整成功恢复 normal，历史错误仍保留；
20. degraded 后完整成功恢复 normal；
21. 当前有效 `SOURCE_DEGRADED` 映射 partial + `is_degraded=true`；
22. 相同时间戳的 partial/degraded 事件优先，无效时间 fail-closed；
23. 11 个来源全部未初始化时 overall unavailable；
24. 部分来源未初始化、其余已初始化来源全部正常时 overall normal；
25. 所有已初始化来源 unavailable 时 overall unavailable；
26. `NO_HOLDINGS` 映射 gate status normal + `blocks_advice=true`；
27. daily review unavailable、portfolio quotes partial 均不得直接设置 `blocks_advice`；
28. gate 任一依赖观察时间更新后 `is_stale=true`，但业务结论不变；
29. 损坏文件 + 成功业务调用：业务成功且事件文件内容、size、mtime 不变；
30. 高版本文件 + 失败业务调用：原业务失败语义不变且事件文件不变；
31. 含额外字段的文件不被下一次写入静默清洗；
32. 并发更新不同 `source_id` 不丢失任何已提交事件。
33. 冻结在相同时钟下 partial → success，写入器自动增加 1 微秒并恢复 normal；
34. 冻结在相同时钟下 blocked → allow，后续成功时间严格更晚且恢复 `blocks_advice=false`；
35. 并发调用经线程锁串行后，同一 `source_id` 的 observation time 严格递增；
36. Gate 允许、四项业务阻断、运行失败和四条恢复路径逐项验证；
37. `SOURCE_NOT_INITIALIZED` 只由 Adapter 合成，事件文件 schema 拒绝持久化该值；
38. 四个按请求来源的 coverage 固定为 `null`，详情包含来源级观察免责声明；
39. `module` 仅接受单个精确值，重复、逗号分隔和未知 module 均返回 422；
40. summary 满足三项质量计数合计 11，`not_initialized` 是 unavailable 子集，stale 可跨状态重叠。

只读测试必须在调用前后比较：

```text
文件集合
文件大小
mtime
SQLite 表集合
```

任何变化均判失败。

### 15.2 API 测试

覆盖：

- 全部正常；
- 部分可用；
- 不可用；
- normal 且 stale；
- partial 且 stale；
- 缓存但 normal；
- 降级但仍可用；
- 现有 gate 阻断建议；
- 来源异常但不阻断建议；
- gate 尚未评估；
- 未知 `source_id` 返回 404；
- 非法 `module/status/is_stale/blocks_advice` 返回 422；
- 重复 `module`、逗号分隔 module 和多 module 请求返回 422；
- 筛选不改变全局状态与全局 gate；
- 单 Adapter 可预期读取失败只降级该来源，其他来源继续返回；
- 注册表、序列化或聚合框架异常固定返回 HTTP 500 和“数据健康服务暂不可用”；
- 内部异常不泄漏敏感信息；
- 两个 GET 不创建事件文件、业务数据库、目录或表。

### 15.3 前端测试

新增建议文件：

```text
frontend/tests/dataHealthView.test.ts
frontend/tests/e2e/data-health-real.browser.mjs
```

覆盖：

- 正常、部分可用、不可用的可见文字；
- stale、缓存、降级标签；
- cache/degraded 为 `null` 时详情显示“当前来源未提供该信息”，列表不得显示“实时数据”；
- 交易日、截止时间、最近成功时间；
- 覆盖数量和“未提供”；
- 建议允许、阻断、尚未评估；
- `NO_HOLDINGS` 显示为已完成评估且阻断，不显示为数据源运行失败；
- gate 依赖更新后同时显示最近结论与“评估已陈旧”；
- 按请求来源卡片显示“最近一次真实调用”，详情显示不代表全部股票或板块均已验证；
- summary 不把 stale/not_initialized 与质量三态绘制成互斥分区；
- 多个阻断原因；
- 空系统引导；
- 加载失败保留旧数据；
- 来源详情与相关页面入口；
- 状态 icon 的 `aria-label` 和非颜色表达；
- 每日复盘、持仓页面轻量入口。

### 15.4 真实后端 E2E

E2E 不 mock `/api/data-health`：

1. 创建临时 `VR_DATA_DIR`、`VR_REPORTS_DIR`、复盘 DB 和证据账本路径；
2. 由测试 fixture 写入一个合法 daily review normal 权威缓存；
3. 通过真实最小事件写入接口构造 `quotes=partial`；
4. 写入一个超过阈值的 `news_radar` 合法缓存，形成 stale；
5. 保持 `announcements` 无事件，形成 unavailable/not initialized；
6. 构造 gate 事件 `HOLDING_QUOTES_UNAVAILABLE`；
7. 启动真实 FastAPI 和构建后的前端；
8. 打开 `/data-health`，验证总体状态和 11 个来源；
9. 验证建议阻断原因；
10. 验证数据时间、缓存和 stale 标签；
11. 打开来源详情；
12. 验证错误摘要不含临时目录、`Traceback`、`sqlite3` 或测试密钥；
13. 比较健康 GET 前后的所有文件 mtime 与 SQLite 表集合，证明严格只读。

## 16. 实现顺序

本设计通过后，单独实现分支按以下顺序推进；本设计 PR 不包含这些代码：

1. 定义 `DataHealthRecord`、稳定错误码和时间归一化测试；
2. 实现独立最小事件存储及只读/原子写测试；
3. 实现 11 个 Adapter，先已有权威状态，后事件来源；
4. 在现有真实业务调用路径增加最小事件记录，不改变业务响应；
5. 实现聚合 service 和两个只读 API；
6. 接入 `app.py` router；
7. 实现 `/data-health` 页面、导航和详情；
8. 接入 `/daily-review` 与 `/portfolio` 轻量入口；
9. 完成后端、前端与真实 E2E；
10. 运行全量离线测试、前端构建和 CI。

每一步都必须保持健康 GET 无副作用；事件记录只随原业务调用发生。

## 17. 风险与已收敛问题

### 17.1 风险

| 风险 | 影响 | 设计内控制 |
|---|---|---|
| 旧模块时间字符串无时区 | stale 误判 | Adapter 明确按来源旧语义解释后统一转 UTC |
| 无完整交易日历 | 节假日可能误标 stale | 使用保守规则、详情披露限制，不误判损坏 |
| 事件写入失败 | 最近状态缺失 | 不影响业务；健康显示未初始化或旧观察状态 |
| 最后一次成功后又失败 | 用户误以为仍正常 | 比较 error/success 时间，失败更新为 unavailable；旧业务数据若权威模块仍可读才允许 partial/degraded |
| 多进程写 JSON | 丢事件 | MVP 明确只支持单应用实例/单 Python 进程；仅使用线程锁，不宣称跨进程安全；多 worker 不在支持范围 |
| 墙上时钟不递增或回拨 | 新成功无法覆盖旧 partial/block | 写入器按 source_id 比较现有最大时间，必要时增加 1 微秒，不依赖自然时钟递增 |
| 健康页面最后 gate 与下一次生成时刻不同 | 放行误解 | 显示“最近评估”，每次生成仍执行现有 gate；gate 记录有 300 秒 stale |
| Adapter 意外调用初始化函数 | GET 产生副作用 | 文件/表/mtime 前后对比测试和只读 SQLite URI |
| 一个事件文件损坏影响多个来源 | 多来源同时 unavailable | 每个来源返回安全损坏状态；不影响直接读取权威状态的 Adapter |

### 17.2 已收敛问题

- **是否主动探测？** 不主动探测，正式排除。
- **是否持久化？** 采用混合方案；仅缺少权威运行元数据的来源写最小事件。
- **存储位置？** 独立 `data_health_events.json`，不复用任何业务数据库。
- **存哪些字段？** 仅 `source_id/last_success_at/last_error_at/last_error_code`。
- **是否保存错误摘要？** 不保存；由稳定 error_code 映射。
- **是否保存覆盖明细？** 不保存；仅在已有权威结果可读时即时填充统一字段。
- **是否由 overall_status 决定建议？** 否；继续使用现有 gate。
- **哪些 Adapter 可写建议字段？** 只有 `portfolio_advice_gate`；其他十个固定 `false/null`。
- **gate 阻断是否代表运行异常？** 否；成功评估出的允许和阻断均为 status normal。
- **缓存/降级未知如何表示？** `null`，不得解释为实时或未降级。
- **按请求来源代表什么？** 只代表最近一次任意真实调用，不代表全部股票或板块已经验证。
- **module 如何筛选？** 只允许单个精确值，多值和逗号分隔均为 422。
- **summary 是否互斥？** 仅 normal/partial/unavailable 互斥且合计 11；stale 正交，not_initialized 是 unavailable 子集。
- **首批范围？** 固定 11 个 Adapter。
- **首批页面入口？** 每日复盘与我的持仓。
- **是否新增刷新 API？** 否。
- **是否建设完整交易日历？** 否；复用北京时间并采用保守工作日规则。

## 18. MVP 验收标准

### 18.1 设计验收

- [x] 现有健康信号已按实际代码位置盘点；
- [x] 质量状态与 stale 分离；
- [x] `normal/partial/unavailable` 有确定定义；
- [x] 11 个首批 Adapter 范围和权威来源明确；
- [x] 每个 Adapter 的缺失、损坏、空数据、partial、stale 和 gate 行为明确；
- [x] 健康 GET 严格只读且有副作用测试；
- [x] 不复制业务数据；
- [x] 混合持久化方案已经收敛；
- [x] 最小事件字段和禁止字段明确；
- [x] API 响应与筛选语义明确；
- [x] 总体状态算法确定；
- [x] 持仓建议 gate 保持现有权威；
- [x] 仅 `portfolio_advice_gate` 可输出建议阻断字段，gate 运行健康与业务结论已分离；
- [x] 缓存/降级采用 `true/false/null`，未知不伪装为实时；
- [x] 事件写入对损坏、高版本、额外字段和未知来源 fail-closed；
- [x] Gate 四类编码、四条恢复路径和严格单调 observation time 已固定；
- [x] 按请求来源的观察范围、coverage=null 和免责声明已固定；
- [x] module 单值筛选与 summary 重叠关系已固定；
- [x] 前端 MVP 和首批页面入口明确；
- [x] 安全错误边界和稳定错误码明确；
- [x] 真实后端 E2E 不 mock 聚合 API；
- [x] P1 提醒和主动探测未混入 MVP。

### 18.2 实现验收

未来实现 PR 必须同时满足：

1. 两个 GET 在空系统、缺文件和损坏场景都不创建或修改任何文件、目录、表或缓存；
2. 11 个 Adapter 均返回结构完整的 `DataHealthRecord`；
3. 状态、stale、缓存、降级和覆盖语义彼此独立，缓存/降级未知均为 `null`；
4. 现有持仓建议 gate 的四项条件和业务行为不变，且仅该 Adapter 可输出建议字段；
5. 事件文件只包含批准的四个字段，无业务响应和原始异常；
6. `/data-health` 同时以文字和视觉标识展示状态；
7. `/daily-review`、`/portfolio` 只增加轻量入口，不删除现有数据；
8. 未知来源 404、非法筛选 422；Adapter 可预期失败局部隔离，框架异常固定安全 500；
9. 真实 E2E 验证 normal、partial、stale、unavailable 和建议阻断；
10. 后端离线测试、前端单元测试、前端构建和 Playwright E2E 全部通过；
11. partial/degraded 可由更晚完整成功恢复 normal，历史错误仍可审计；
12. 全部未初始化、可选未初始化和已初始化全不可用三种 overall 语义均通过测试；
13. 损坏、高版本或额外字段事件文件不会被下一次业务调用覆盖或清洗；
14. gate 依赖更新只将最近评估标 stale，不篡改允许/阻断结论。
15. Gate 允许、阻断、运行失败和恢复均按专用事件编码稳定映射；
16. 同一来源的每次 observation time 严格递增，冻结时间下也能恢复；
17. 四个按请求来源只表达最近一次真实调用，coverage 为 null 且不泄露请求对象；
18. module 只允许单个精确值，summary 三态合计 11，重叠统计关系有前后端测试。
