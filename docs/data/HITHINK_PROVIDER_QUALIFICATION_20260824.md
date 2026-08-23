# HiThink Production Provider Qualification（2026-08-24）

> 任务：DATA-HITHINK1 / [GitHub #207](https://github.com/guilaile95/Vibe-Research/issues/207)<br>
> 证据范围：HiThink-Tech 官方仓库、官方文档站、官方示例、本仓库 PR #79 历史，以及本次受控 credentialed live qualification。<br>
> 本文状态：`DOC_VERIFIED + LIVE_VERIFIED + DATASET_LEVEL_CUTOVER_IMPLEMENTED`。API Key 只从环境变量读取；未输出、持久化、提交或写入命令参数。Live 原始大结果仅存本机临时目录，仓库只记录有界摘要。

## 1. 结论先行

- **官方文档证明的是公开能力面，不是 production qualification。** 当前官方 REST 契约列出 59 个 GET 端点，覆盖 A 股、指数/板块、公募基金和 Market Dumps；但官方自己明确说明，静态契约不能证明当前连接或账号权限，只有授权请求才能完成线上验证。[REST 契约](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/README.md) · [MCP 边界](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/mcp.md)
- **Market Dumps + marketdb 是值得 live qualification 的 bulk/local-research 候选。** 官方提供全量、近 10 交易日增量和复权事件三个 Parquet dump，并提供本地 DuckDB 的全量/增量同步、校验、查询和导出路径；这仍不使 marketdb 自动成为 Vibe Canonical Fact Authority。[Market Dumps](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/endpoints-market-dumps.md) · [marketdb](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/python/toolkit/marketdb/README.md)
- **生产法律门槛尚未关闭。** 仓库代码为 MIT；在本次检查到的官方公开材料中，没有找到 API 返回数据的明确许可、长期留存期限/权利、再分发/转售权、商业使用条款、收费表或 SLA。它们必须保持 `UNKNOWN`，不能把软件 MIT 许可外推为数据许可。[仓库 LICENSE](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/LICENSE)
- **当前文档存在一处必须 live 关闭的错误码冲突。** 通用 REST 契约使用 `2001/2003/3002`，Market Dumps 专页却写 `2002/2004/4040`；不能在适配器里提前固化其中一组为唯一事实。
- **官方 best-practice / inspirations 只能作为产品模式参考。** 官方明确说示例用于说明数据组合方式，不是能力契约；截图与静态 HTML 只展示一种可能效果。`BK11_BEST_PRACTICE_USE = BENCHMARK_ONLY`，不得把示例当作 BK11 数据质量、实时权限、production routing、策略有效性或投资结论的证据。[官方 README](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/README.md) · [Inspirations](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/examples/inspirations/README.md)
- **本次账号的核心高价值能力已完成 live qualification。** 33 个受控 JSON 观测中，32 个业务成功；唯一非 PASS 是故意发送的非法 symbol，实际返回 `code=1002`，而非文档示例暗示的 `3001`。未触发权限拒绝或限流。
- **唯一 production primary cutover 是运行时未复权日线。** Stable 既有 `astock.kline` 对两只代表标的实测均在 mootdx 传输层失败；HiThink 对 SSE、SZSE 和真实 BSE 标的均返回严格升序、无重复的日线。实现仅在 `category=4` 且 credential 存在时优先走 HiThink；SSE/SZSE 失败保留 mootdx，当前 `920xxx` BSE 因 mootdx 会错路由而 fail closed。Tushare Fact Lake canonical authority、周/月/分钟 K 线和正式投资事实均未改变。

## 2. 证据标记

- `CONFIRMED_DOC`：由下列固定 SHA 的官方一手材料直接支持。
- `CONFIRMED_HISTORY`：由本仓库 GitHub PR 历史直接支持，但不代表当前 stable 或当前 provider 行为。
- `UNKNOWN`：官方公开材料未给出，或不同官方页面互相冲突；必须等待 live evidence 或正式条款。
- `PRODUCT_JUDGMENT`：Vibe-Research 的产品/架构解释，不声称是 provider 事实。

## 3. 官方仓库版本钉住

| 项目 | 结论 | 证据 |
|---|---|---|
| 默认分支 / HEAD | `main` / `9dbef74d2ce535857e610eec265bcb9302942d48`（2026-08-24 通过官方 Git remote `ls-remote` 核验） | [固定 commit](https://github.com/HiThink-Tech/Financial-API/commit/9dbef74d2ce535857e610eec265bcb9302942d48) |
| 官方快照时间 | commit message 声明 `2026.08.17.1`，快照时间 `2026-08-17 17:16 CST` | [固定 commit](https://github.com/HiThink-Tech/Financial-API/commit/9dbef74d2ce535857e610eec265bcb9302942d48) |
| 最新 release / tag | `v0.1.5`；annotated tag 解引用后与上述 HEAD 相同 | [v0.1.5 release](https://github.com/HiThink-Tech/Financial-API/releases/tag/v0.1.5) |
| release 主要变化 | 集合竞价、跌停/炸板、基金公司/经理/业绩/财务/资讯/发行/历史持仓扩展；REST、MCP、CLI、Python 与 Skill 同步 | [commit / changelog diff](https://github.com/HiThink-Tech/Financial-API/commit/9dbef74d2ce535857e610eec265bcb9302942d48) |

本文所有 GitHub 官方文档链接均固定到该 SHA，避免 `main` 后续漂移。线上聚合文档入口是 [official `llms-full.txt`](https://fuyao.aicubes.cn/llms-full.txt)，但仓库说明 `docs/api/` 才是仓库内唯一 REST 契约源，且该聚合文本不是 OpenAPI 等机器契约源。[文档治理](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/README.md)

## 4. 认证与配置约定（`CONFIRMED_DOC`）

- Base URL：`https://fuyao.aicubes.cn`；当前公开数据端点均为 `GET`。
- REST / MCP 使用请求头 `X-api-key`。成功必须同时满足 HTTP 200 与业务信封 `code == 0`；信封为 `{code, message, request_id, data}`，业务错误时 `data` 为 `null`。[通用协议](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/README.md)
- 推荐统一变量名是 `HITHINK_FINANCE_API_KEY`。Skill 的查找顺序是：安全临时输入 → 推荐环境变量 → 用户级 `credentials.env` → 旧版兼容来源；`FUYAO_TOKEN` 和 `API_KEY` 仅为兼容，不应用于新配置。[官方 Skill](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/skills/hithink-finance/SKILL.md)
- 用户级凭据文件约定：Windows `%APPDATA%\hithink-finance\credentials.env`，macOS `~/Library/Application Support/hithink-finance/credentials.env`，Linux `${XDG_CONFIG_HOME:-~/.config}/hithink-finance/credentials.env`。
- CLI 对 Agent/CI 推荐 stdin 或进程环境变量，凭据副本进入系统凭据库；禁止把 Key 写入参数记录、配置、Markdown、日志、Prompt、Issue、产物或 Git。[CLI auth](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/hithink-finance-cli/README.md)
- MCP 共有四个托管端点，使用客户端 Secret 或环境变量插值：A-share、A-share-index、meta、fund。[MCP 配置](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/mcp.md)

**本任务安全结论：** `LIVE_AUTH = PASS`。凭据只从 `HITHINK_FINANCE_API_KEY` 读取并进入 `X-api-key` header；探针、生产客户端、测试、报告、命令参数、输出和 Git diff 都不含凭据值。账号 capability 只按下文逐数据集的 live 结果认定，不从认证成功外推。

## 5. 官方公开 dataset / endpoint 能力面

官方固定 SHA 的 [capability map](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/capability-map.md) 列出 **59 个 REST GET 端点**：

| 类别 | 数量 | 端点 |
|---|---:|---|
| 元信息 | 2 | `/api/meta/tickers/search`; `/api/meta/tickers/list` |
| A 股行情 / 公司行为 | 3 | `/api/a-share/prices/snapshot`; `/api/a-share/prices/historical`; `/api/a-share/corporate-actions/adjustment-factors` |
| 财务 | 4 | `/api/a-share/financials/income-statements`; `/balance-sheets`; `/cash-flow-statements`; `/indicators` |
| 估值 | 1 | `/api/a-share/valuations/snapshot` |
| 交易日历 | 1 | `/api/a-share/calendar/trading-days` |
| 集合竞价 | 2 | `/api/a-share/auction/snapshot`; `/api/a-share/auction/short-term-benchmark` |
| 指数 / 板块 | 4 | `/api/a-share-index/catalog/ths-index-list`; `/constituents/ths-stock-list`; `/prices/snapshot`; `/prices/historical` |
| 公募基金 | 28 | `/api/fund/profile/detail`; `/portfolio/holdings`; `/performance/nav`; `/performance/returns`; `/holders/detail`; `/market/snapshot`; `/market/historical`; `/companies/detail`; `/portfolio/industry-allocation`; `/performance/indicators-historical`; `/performance/drawdowns`; `/holders/top`; `/corporate-actions/dividends`; `/diagnostics/detail`; `/financials/indicators`; `/financials/income-statements`; `/financials/balance-sheets`; `/managers/investment-style`; `/managers/performance`; `/managers/experience`; `/managers/detail`; `/news/article-list`; `/offerings/list`; `/portfolio/stock-history`; `/portfolio/stock-report-dates`; `/portfolio/bond-history`; `/portfolio/bond-report-dates`; `/portfolio/asset-allocation` |
| A 股特色数据 | 11 | `/api/a-share/special-data/limit-up-pool`; `/limit-down-pool`; `/limit-break-pool`; `/limit-up-ladder`; `/anomaly-analysis-list`; `/anomaly-analysis-stock`; `/skyrocket-list`; `/hot-stock-list`; `/hot-stock-list-history`; `/hot-stock-rank-trend`; `/dragon-tiger-list` |
| Market Dumps | 3 | `/api/dump/market-dumps/daily-k/download-url`; `/daily-k-10d/download-url`; `/adjustment-factors/download-url` |

补充边界：公开能力不覆盖分钟 K、tick、Level-2、港股、美股、期货、期权；财务指标不提供行业均值/评分/排名；异动分析只有当日快照。仓库总览还把宏观、新闻/公告原文、研报原文列为未公开范围。[能力边界](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/capability-map.md) · [README](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/README.md)

这些是 `DOCUMENTED_AVAILABLE`，不是 `LIVE_VERIFIED`。每个 dataset 的账号 entitlement、时间深度、字段完整度、延迟、分页、修订语义、空集语义和 rate-limit 阈值仍需实测。

## 6. Market Dumps / marketdb 模型

### 6.1 Market Dumps（`CONFIRMED_DOC`）

| dump | 文档内容 / 规模 | 目标用途 |
|---|---|---|
| `daily-k` | 全 A 股约 10 年、原始未复权日 K，约 945 万行 | 首次全量 |
| `daily-k-10d` | 最近 10 个交易日，约 25 万行 | 日常增量 |
| `adjustment-factors` | 分红/送股/配股等复权事件，约 5.2 万行 | 复权计算 |

官方流程是：授权 GET 签出 S3 预签名 URL → 在约 5 分钟有效期内再次 GET 下载 Parquet → pandas / pyarrow / DuckDB 读取；预签名 URL 不应持久化或作为长期地址。[Market Dumps contract](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/endpoints-market-dumps.md)

### 6.2 marketdb（`CONFIRMED_DOC`）

- 本地模型是 Python + DuckDB，面向历史 OHLCV、复权、全市场 panel、只读 SQL 和 CSV 导出；实时行情与财报走远端 toolkit。
- 公开入口包括 CLI、`marketdb.MarketDB` SDK，以及 `v_daily` / `v_daily_qfq` / `v_daily_hfq` / `v_symbol` 视图。[marketdb overview](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/python/toolkit/marketdb/README.md)
- `auto-sync` 文档策略：空库 → FULL；落后不超过 7 个交易日 → 10 日增量合并；落后超过 7 个交易日 → FULL；复权事件每次重拉；临时 Parquet 应用后删除。[sync model](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/python/toolkit/marketdb/README.md)
- 官方把 marketdb 描述为可“保存长期历史行情”、本地增量同步和文件导出。这确认了产品的本地留存功能，但**不是**对 API 数据长期保留或再分发的法律授权。[local storage use](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/README.md)

**live qualification 需关闭：** dump entitlement；真实大小/时间覆盖；Parquet schema、主键、排序、重复与 checksum/manifest；预签名 URL expiry；FULL/INCREMENTAL 幂等性；复权重建；失败恢复；当前账号的速率限制。

## 7. 错误、权限与空值行为

### 7.1 通用契约（`CONFIRMED_DOC`）

| code | 官方含义 | 预期处理 |
|---:|---|---|
| `0` | 成功 | 使用 `data` |
| `1001` / `1002` / `1003` / `1004` | 必填缺失 / 格式无效 / 超范围 / 参数冲突 | 修正调用，不原样盲重试 |
| `2001` | 未认证 | 检查请求头 |
| `2003` | 无权限或 Key 无效 | 检查账号授权或重新签发 |
| `3001` | 标的不存在 | 先 meta 消歧 |
| `3002` | 数据未准备 | 保留 `request_id`，稍后再查；不得补零或伪造 |
| `3004` | 资产类型不支持 | 改用适用端点，不原样重试 |
| `4001` | 限流 | 指数退避，最多 3 次 |
| `5001` / `5002` / `5003` | 服务端或上游异常 | 有界退避；持续失败时保留 `request_id` |

`null` 表示未披露或上游无值，不得自动补零；错误时 `data=null` 不能解释为成功空集。[错误契约](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/README.md)

### 7.2 已发现的官方文档冲突（`UNKNOWN`）

Market Dumps 专页把认证失败写成 `2002/2004`，把数据未就绪写成 `4040`，与通用契约的 `2001/2003/3002` 不一致。[Market Dumps response](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/endpoints-market-dumps.md)

因此 production adapter 应先保留 provider 原始 code/message/request_id，并在 live qualification 后才决定稳定分类；当前不能把任一套文档码硬编码为唯一事实。官方同时说明，数据权限、调用频率和 capability 以官网与账号授权为准，没有公开固定 quota 数字。[账号授权边界](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/README.md)

## 8. 数据许可、留存、再分发、收费与 SLA

| 事项 | 状态 | 证据 / 解释 |
|---|---|---|
| 仓库代码与文档许可 | `CONFIRMED_DOC` | 仓库为 MIT，允许对“Software and associated documentation”使用、复制、修改与分发，并附 MIT 的条件和免责。[LICENSE](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/LICENSE) |
| API 数据的独立许可 | `UNKNOWN` | 公开仓库 MIT 文本没有把 API 返回的金融数据定义为受许可 Software，也未给出独立 data license。不得外推。 |
| 本地/长期留存权与期限 | `UNKNOWN` | 官方提供长期本地数据库这一技术能力，但未在已检查公开材料中说明法律留存期限、账号终止后的保留权或删除义务。 |
| 内部研究/商业使用 | `UNKNOWN` | 产品面向研究者和应用开发者不等于明确商业数据授权；未找到可执行的商业使用条款。 |
| 再分发、转售、公开展示原始数据 | `UNKNOWN` | 未找到允许或禁止的明确公开条款，production 对外分发前必须取得正式授权。 |
| 基金资讯原文 | `CONFIRMED_DOC_LIMIT` | 官方只提供公开文章元数据，并明确元数据不等于新闻原文授权；应按返回 URL 和账号权限使用。[fund endpoint boundary](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/docs/api/endpoints-fund.md) |
| 定价、quota、SLA、支持/补偿 | `UNKNOWN` | 公开材料只说权限和调用频率以账号授权为准；未找到价格表、保证的可用性/延迟/更新时点或服务补偿条款。 |

检查方法：对固定 SHA 的官方仓库公开文本做全量关键词审计，并检查官方 `llms-full.txt`、README、REST/MCP/marketdb/Market Dumps/Skill 文档。该结论仅表示“本次审阅的公开一手材料没有提供”，不表示 provider 私有合同一定不存在。

**生产 Gate：** 在许可、留存、再分发、商业使用和收费/SLA 获得官方书面条款或账号合同前，相关字段一律保持 `UNKNOWN`；不得将 HiThink 升级为全面 Primary Provider，也不得把原始数据对外再分发。本地单用户、有限数据集的 runtime 读取不因此被误标为“已获商业再分发许可”。

## 9. Best-practice 产品模式与 BK11 边界

### 9.1 已确认的官方事实

- 官方 inspirations 提供 16 个 Prompt/静态 HTML 组合示例；官方明确写明截图与示例 HTML 只是“一种可能效果”，不是模板。[Inspirations index](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/examples/inspirations/README.md)
- 官方 README 更直接说明：“示例用于说明数据组合方式”，不是数据能力契约、投资建议或固定视觉标准。[README examples](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/README.md)
- 本地全市场研究示例本身要求平台登录态、dump 权限和本地 DuckDB；静态示例不能证明目标账号具有这些条件。[advanced inspiration](https://github.com/HiThink-Tech/Financial-API/blob/9dbef74d2ce535857e610eec265bcb9302942d48/examples/inspirations/README.md)

### 9.2 Vibe 产品解释（`PRODUCT_JUDGMENT`）

`HITHINK_BEST_PRACTICES = PRODUCT_PATTERN_EVIDENCE_ONLY`

可借鉴：先消歧再取数、事实时间/复权口径/来源标注、缺失不补零、大结果落盘、研究面板交互、分析与投资建议分离。

不可推导：当前账号 live 权限、provider SLA、数据正确性/完整性、历史成分语义、财报 revision、策略 alpha、production readiness 或 canonical authority。

`BK11_BEST_PRACTICE_USE = BENCHMARK_ONLY`

对 BK11 只参考研究工作流、视图层级、筛选/对比交互与 caveat 表达；不得据此替换 BK11 已批准事实链，不得把静态示例当 ingest evidence，不得把热榜/涨停/龙虎榜示例输出升级为确定性买卖信号。任何 BK11 provider/routing 变化仍需 dataset-level live evidence、Vibe canonical contract 和单独实现授权。

## 10. PR #79 历史复用边界

本仓库 [PR #79](https://github.com/guilaile95/Vibe-Research/pull/79) 是 `CONFIRMED_HISTORY`：截至 2026-08-24 仍为 **OPEN / 未合并**，不是 stable 事实。PR body/commits 记录 2026-08-10 的受控 live smoke：最终 rotated credential rerun 为 11/11 live tests PASS，并观察到 invalid search 与非交易日为成功空集、财报 revision semantics 为 `UNKNOWN`、provider response 只作为 Observation。

这批历史证据可复用为回归样例和探针安全纪律，但不能替代当前 qualification，原因是：

1. PR #79 未进入 stable；
2. 它核验时的官方仓库基线早于当前 `9dbef74` / `v0.1.5`；
3. 当前版本已新增/扩展竞价、特色数据和大量基金能力；
4. entitlement、Key 状态、数据内容和服务行为都可能变化。

因此：`PR79_REUSE = TEST_PATTERN_AND_HISTORICAL_EVIDENCE`，`PR79_CURRENT_PRODUCTION_PROOF = NO`。

## 11. Credentialed live qualification 验收项

上述项目已在 §12–§16 逐项关闭；仍无法从 provider 公开材料证实的 revision、quota、SLA 和数据许可继续保持 `UNKNOWN`。

## 12. Live qualification 方法与安全边界

- 执行日：2026-08-24；官方仓库固定在 `9dbef74d2ce535857e610eec265bcb9302942d48`。
- 探针：`tools/research/hithink_qualification_probe.py`。所有请求只从环境读取 Key；JSON 只保存 endpoint、HTTP/business code、request-id 是否存在、延迟、字段/类型、有限 identity、时间范围、空值、顺序与重复摘要。
- 调用规模：33 个高价值 JSON 观测，外加三个 dump 签名、三个实际 Parquet 下载和每个成功下载后的重新签名检查；没有压力测试、没有遍历全市场逐只 REST。
- 结果：32/33 业务成功，`DENIED=0`、`NOT_AVAILABLE=0`。唯一非 PASS 是故意使用 `999999.ZZ` 的错误语义探测，HTTP 200 + `code=1002` + request_id；它证明错误信封可解析，也证明 live code 与通用文档示例不能机械等同。
- 延迟：JSON 观测约 45.8–313.4 ms，平均约 76.7 ms。该样本只证明本次受控运行，不构成 SLA。
- Rate limit：本轮未观察到 `4001`；未执行 stress test，因此阈值、burst 和长期配额均为 `UNKNOWN`。
- 原始 JSON、预签名 URL、header 与 Key 均未落库。三个 Parquet 只保留在本机临时目录，不进入 Git、Issue、PR 或 Notion。

## 13. Capability results 与 dataset classification

| 能力 | Live 证据 | 状态 | Dataset 决策 |
|---|---|---|---|
| Security resolution | 中文名和 6 位代码均唯一解析到 `600519.SH`；市场 dump 动态发现 `920000.BJ` 后，meta 精确搜索返回“安徽凤凰”且 exchange=`BJ` | `PASS_WITH_FILTER_DRIFT` | `KEEP_CURRENT_PROVIDER`：Vibe 版本化官方 exchange policy 保持 authority；HiThink 只提供存在性/provider alias 观测 |
| BSE meta list | `exchange=BJ&asset_type=a-share` 返回 `code=0`，但错误给出 SH 标的；带 BJ filter 的前缀搜索为空；对 dump 发现的精确代码搜索则成功 | `PASS_PARTIAL / CONTRACT_DRIFT` | 生产日线只接受 canonical policy 已解析的当前 `920xxx`；legacy BSE 不猜映射 |
| Trading calendar | 242 个严格升序 session，滚动覆盖约一年 | `PASS` | `VERIFIER_CANDIDATE`；现有多年度 offline deterministic calendar 继续 primary |
| Latest snapshot | `600519.SH`、`000001.SZ`、`920000.BJ` 三个请求 identity 全部返回 | `PASS` | `VERIFIER_CANDIDATE`；Tencent/current runtime 不在本 PR 切换 |
| Daily bars short/long | 15-session short window；`600519.SH` 长窗 2,340 bars（2017-01 至 2026-08），严格升序、零重复、OHLC/volume/turnover 类型闭合 | `PASS` | `PRIMARY_CANDIDATE` → 本 PR 实际切换 `astock.kline(category=4)` runtime primary |
| Daily bars BSE | 动态发现的 `920000.BJ` 返回 15 条短窗日线，严格升序、零重复 | `PASS` | 纳入当前 `920xxx` production daily route；legacy BSE 保持 unsupported/fallback |
| Adjustment modes/events | none/forward/backward 各返回一致窗口；单股公司行动 14 条，按 ex-date 降序、零重复 | `PASS` | `SPECIALIZED_ONLY`；未混入 unadjusted daily dataset |
| Income statement | 5 期年报，含 period/report date/fiscal identity 和 21 字段 | `PASS` | `VERIFIER_CANDIDATE`；无 revision/vintage，保持当前 provider |
| Balance sheet | 5 期年报、15 字段，与 income 的 period_end 对齐 | `PASS` | `VERIFIER_CANDIDATE`；不替换 Tushare restatable identity |
| Cash-flow statement | 5 期年报、14 字段，与其它两表 period_end 对齐 | `PASS` | `VERIFIER_CANDIDATE`；不把 report_date 冒充公告/known-at time |
| Financial indicators | 五个固定 ability block，共 29 个指标；一个 upstream null 被原样保留 | `PASS` | `VERIFIER_CANDIDATE`；行业均值/评分/修订仍不可用 |
| Valuation | 两只股票 latest snapshot 返回五项固定估值；timestamp 是返回集合的最新有效上游时间 | `PASS` | `VERIFIER_CANDIDATE`；latest-only，不进入历史/PIT authority |
| Concept/industry/index | concept 390、industry 320；两个动态选中指数的当前成分分别 1,065/30；index snapshot 和 154-session history 成功 | `PASS` | `SPECIALIZED_ONLY`；THS taxonomy 不等价于 EastMoney taxonomy，不能自动替换 |
| Limit-up/ladder | 历史涨停池 20 条样本含连续天数/原因/封单字段；ladder 返回固定 30-session window | `PASS` | `VERIFIER_CANDIDATE`；`KEEP_EASTMONEY`，不削弱 BK11 的 N/M/reason/history/replay |
| Anomaly | REST envelope 成功，但本次受控时点 list/stock 均为空 | `PASS_EMPTY` | `SPECIALIZED_ONLY`；空集不是能力错误，也不足以证明异动覆盖质量 |
| Market Dumps | 三类签名、下载、DuckDB read、重复签名恢复均成功 | `PASS` | `SPECIALIZED_ONLY / RESEARCH_DATA_PLANE_CANDIDATE`；不是 Canonical Fact authority |

### Temporal / revision / NULL 结论

- Daily/index bars 的事实时间是 `date_ms`（Asia/Shanghai 00:00），结果严格升序；retrieval time 由本地探针 UTC 生成，二者不混用。
- 三张财报按 `period_end_ms` 降序；`report_date_ms` 存在，但没有足够证据把它定义为公告时间或 point-in-time known-at 时间。
- 所有测试能力均未暴露 revision id/data version；财报 revision semantics 保持 `UNKNOWN`。
- Provider `null` 保留为 `null`，不补零。财务指标 live 样本实际观察到一个 null。
- Current constituents/latest snapshot/latest valuation 只按 snapshot 使用，不制造历史成员或历史估值。

## 14. Market Dumps / Research Data Plane 实测

| Dump | 下载与范围 | DuckDB 结果 | 质量发现 |
|---|---|---|---|
| `daily-k` | 179,879,937 bytes；约 183.5 秒；2016-08-23 至 2026-08-21 | 10,232,341 rows；5,548 securities；11 列与官方 schema 一致 | `(thscode,date_ms)` 零重复；identity/date 零 null |
| `daily-k-10d` | 1,079,396 bytes；2026-08-10 至 2026-08-21 | 55,400 rows；5,549 securities；其中 338 个 `.BJ` identities | `(thscode,date_ms)` 零重复；identity/date 零 null |
| `adjustment-factors` | 295,136 bytes；1991-02-26 至 2026-08-28（含未来已知 ex-date） | 56,983 rows；5,418 securities；其中 296 个 `.BJ` identities | 发现 1 个完全重复事件键：`000601.SZ` / 1997-11-04，任何 ingest 前必须确定性去重 |

Operational findings：

- 三个签名端点均 `HTTP 200 + code=0`；`MARKET_DUMPS_PERMISSION = PASS`。
- 预签名 URL 的 `HEAD` 返回 403，但同一 URL 的 `GET` 下载成功，说明签名限制了 method；不能把 HEAD 403 误判为 entitlement denial。
- 每次下载后重新调用签名端点均成功并返回新 URL；`FAILURE_RECOVERY_RESIGN = PASS`。没有等待 URL 真正过期，因此“过期后重签”按官方契约 + 重签路径验证，实际 expiry failure injection 仍为 `NOT_RUN`。
- Full 与 10d schema 相同；10d 比 full 多一个 active identity 是真实观察，原因未证明，不做错误归因。
- Dump 是 bulk Research Data Plane 候选，不自动形成 `ProviderObservation`、immutable vintage、Canonical Fact 或 Formal Decision authority；本 PR 不把官方 mutable UPSERT 直接复制进 Fact Lake。

`MARKET_DUMPS = PASS`<br>
`RESEARCH_DATA_PLANE = QUALIFIED_SPECIALIZED_CANDIDATE`<br>
`MARKETDB_PRODUCTION_DEPENDENCY = NO`

## 15. Current-provider comparison 与 production cutover

### 15.1 小样本比较

同一 stable base、同一运行环境，对 `600519` 和 `000001` 各请求 20 条 daily bars：

- 既有 runtime primary `mootdx`：两只均在 response-header transport 阶段失败，未获得 bars。
- HiThink：两只均返回 20 条，覆盖 2026-07-27 至 2026-08-21，provider identity、unadjusted 口径、日期顺序与字段类型全部闭合。
- BSE：从 HiThink 10d dump 动态发现 `920000.BJ`，meta 精确解析为真实当前证券，snapshot 和 20 条 production daily route 均成功。

这项比较证明的是“当前 live runtime 可用性差异”，不是价格绝对正确性或 provider SLA。由于 mootdx 没有返回可比较数值，本轮没有把“无法对数”伪装成一致性 PASS。

### 15.2 实际切换边界

`CUTOVER_DATASETS = runtime_a_share_daily_bars_unadjusted`

- 新增窄客户端 `backend/hithink_finance_client.py`，固定单一 qualified endpoint，不建立通用 provider framework。
- `astock.kline(category=4)` 在 credential 存在时以 HiThink 为 preferred runtime primary；只接受现有 canonical exchange policy 解析的 SSE/SZSE 与当前 `920xxx` BSE。
- Provider payload 必须满足 HTTP 200 + `code=0`、identity、`interval=1d`、`adjust=none`、请求窗口、上海零点、严格升序、无重复、有限 OHLC/volume/turnover 与 OHLC invariants；否则整次 observation 被拒绝。
- 输出复用既有 `datetime/date/open/high/low/close/vol/volume/amount` 契约，并显式携带 `provider_id`、`provider_symbol`、`price_adjustment=none` 与 provider contract。
- SSE/SZSE 在未配置 Key、transport/business/schema 失败时回退既有 mootdx；失败 observation 不被消费。
- 当前 `920xxx` BSE 在未配置 Key 或 HiThink 失败时 fail closed，因为已锁定的 mootdx 会把 `920000` 错判为上海。Legacy BSE 没有 provider old→new identity 证据，保持既有路径但不纳入本次 HiThink production coverage。
- `category=5/6/11` 仍使用 mootdx；HiThink 不支持的周期没有被伪造。
- `tushare_daily_shadow`、`security_price_point_authority`、Fact Lake canonical route、Holding/Trade/Frozen Decision/Formal Decision/Thesis authority 全部未修改。

因此：

`HITHINK_PRIMARY_PROVIDER = DATASET_LEVEL_ONLY`<br>
`PRIMARY_HITHINK_DATASETS = runtime_a_share_daily_bars_unadjusted`<br>
`VERIFIER_HITHINK_DATASETS = security_identity_observation, trading_calendar, snapshot, financial_statements, financial_indicators, valuation, limit_up`<br>
`KEEP_EASTMONEY_DATASETS = bk11_limit_up_pool, board_ranking, eastmoney_taxonomy`<br>
`KEEP_TUSHARE_DATASETS = fact_lake_daily, financial_indicator_revision_identity, bk11_count_verifier`<br>
`KEEP_OTHER_PROVIDER_DATASETS = deterministic_security_policy, offline_trade_calendar, tencent_snapshot, baidu_valuation_percentile, mootdx_non_daily_and_fallback`<br>
`DENIED_DATASETS = NONE`<br>
`NOT_AVAILABLE_DATASETS = minute_bars, tick, level2, historical_constituents, historical_valuation, provider_revision_vintage`<br>
`PRODUCTION_CUTOVER = IMPLEMENTED_LOCAL_GATE_PASSED`

## 16. External reuse / license / secret ledger

- Repository：`HiThink-Tech/Financial-API`。
- Pinned commit：`9dbef74d2ce535857e610eec265bcb9302942d48`；release `v0.1.5`。
- Repository license：MIT，**只**用于仓库代码/文档判断；没有复制或 vendoring 官方 runtime/toolkit 代码。
- Reused：固定 REST endpoint、header auth 名称、success envelope、daily field contract、Asia/Shanghai date semantics、adjustment enums、dump Parquet schema。
- Not reused：官方 mutable marketdb UPSERT、credential files、MCP/CLI、通用 retry framework、任何 provider secret 或原始数据。
- Data license：`UNKNOWN`；长期留存、商业使用、再分发、定价、quota、SLA 均 `UNKNOWN`。Vibe 不对外再分发 raw dump。
- Best practice：`PRODUCT_PATTERN_EVIDENCE_ONLY`；BK11 只 benchmark，不因案例切换 canonical。
- Secret rule：Key 只从环境读取；所有携带 `X-api-key` 的请求固定 origin 且 `allow_redirects=False`，避免自定义 header 被 30x 转发；预签名下载同样不跟随 redirect；client/probe 只生成 credential-safe errors/summaries；最终 merge 前必须再次扫描 diff、commit log、测试与临时输出。

### 16.1 Local Gate evidence

- Offline full backend regression（在最终 trust-boundary guards 前）：`7,185 passed, 8 skipped, 12 deselected`；guards 后 targeted contracts：`21 passed`；相关 astock/exchange contracts：`123 passed`。
- Live runtime smoke（guard 后）：`600519.SH`、`000001.SZ`、`920000.BJ` 各返回 20 条未复权日线，均携带 `provider_id=hithink_financial_api` 与正确 `provider_symbol`。
- Independent review 发现并关闭三个 blocker：current BSE 禁止错误 mootdx fallback；credential-bearing 与 presigned URL 请求禁止自动 redirect；provider business code 必须是 exact integer，非整数值不得进入错误或持久化摘要。
- Final Codex Security working-tree diff scan `702d5c6a-5e7a-418d-8869-c48254dea61a`：3/3 executable surfaces reviewed，`0 findings`，coverage complete。
- Secret scan：6 个变更文件、working diff 与 HiThink 临时 JSON/Markdown/text/log summary 的 exact credential 命中均为 0；通用 secret pattern 命中为 0。

---

**Research status:** `PRIMARY_SOURCE_RESEARCH_COMPLETE`<br>
**Live API status:** `LIVE_VERIFIED`<br>
**Credential exposure:** `NONE`<br>
**Production provider conclusion:** `DATASET_LEVEL_PRIMARY_FOR_RUNTIME_DAILY_BARS_ONLY`<br>
**Canonical Fact authority change:** `NO`<br>
**Market dumps:** `QUALIFIED_SPECIALIZED_CANDIDATE`<br>
**Secret leak:** `NO`
