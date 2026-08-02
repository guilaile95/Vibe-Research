# BK-11 Slice 0：短线市场事实数据与口径可行性审计

| 项 | 值 |
|----|-----|
| 分支 | `research/bk11-short-term-facts-feasibility-v0.1` |
| Base | `463dd6b6c375e20003fe07af73ae2faf69136ee3` |
| 状态 | Slice 0 审计交付（CONDITIONAL GO） |
| 范围 | 仅审计，不实现产品页面 |
| 时区 | Asia/Shanghai |

---

## 1. Executive Decision

### CONDITIONAL GO

整体决策为 `CONDITIONAL GO`。Slice 1 仅允许实现市场宽度、涨停数量、跌停数量、炸板数量、基础 break/seal 比例。其余指标（晋级率、premium、loss_effect、seal quality、题材结构、历史回补、T+1 闭环）在合同未完成验证前继续阻断。

进入 Slice 1 的硬约束：

```text
- 来源许可仍为 unclear，仅用于受控研究环境
- 保留 provenance（source_id / trade_date / fetched_at / snapshot_at）
- Data Health 可降级，合法零值不判失败
- 不实现未通过指标
- Tier A 核心来源缺失，所有数据均来自 Tier B/C
```

---

## 2. Scope and Non-goals

### 2.1 Scope

```text
- 审计短线市场事实指标的数据源可用性、口径明确性、许可边界
- 定义市场宽度、涨跌停、炸板、连板梯队、晋级率、溢价、亏钱效应、题材结构的合同
- 提供离线 fixture 合同供 Slice 1+ 单元测试
- 定义 Data Health 映射、Preflight 规则、缓存策略
```

### 2.2 Non-goals

```text
- 不实现任何生产代码、API、前端页面、数据库、Data Health Adapter、调度器
- 不修改 router/app
- 不引入新依赖
- 不做历史回补审计（Slice 4 范围）
- 不做 T+1 闭环验证（Slice 4 范围）
- 不把 C 的复审数字直接冒充为 Q 的机械验证结果
```

---

## 3. Existing Vibe-Research Reuse Points

| 能力 | 文件 | 函数 | 复用状态 |
|------|------|------|---------|
| 涨停板四池原始请求 | `backend/astock.py` | `em_zt_topic_pool()` | 已实现，Slice 1 复用 |
| 短线情绪计算 | `backend/market.py` | `_emotion()` | 已实现，需按本合同重构 |
| 市场广度纯计算 | `backend/market.py` | `calculate_market_breadth()` | 已实现，Slice 1 复用 |
| 市场广度状态信封 | `backend/market.py` | `get_market_breadth()` | 已实现，Slice 1 复用 |
| Data Health Adapter 基类 | `backend/data_health_adapters.py` | `AdapterReadError` | 已实现，Slice 1 复用 |
| Data Health 服务 | `backend/data_health_service.py` | — | 已实现，Slice 1 复用 |
| 东财统一限流入口 | `backend/astock.py` | `em_get()` | 已实现，复用 |

---

## 4. Source Tier Matrix

### 4.1 Tier 定义

```text
Tier A: 交易所、监管机构或正式官方公开数据
Tier B: 商业数据供应商公开接口或公开页面
Tier C: 社区库、包装器、逆向客户端或非正式来源
```

不得以"零鉴权、项目已实现、已实测"作为 Tier A 依据。无需 API Key 只表示访问方式，不代表许可。

### 4.2 来源分级

| source_id | Tier | 依据 |
|------|------|------|
| eastmoney_limit_pool | Tier B | 商业数据供应商（东方财富）涨停板四池公开接口，非交易所直发 |
| eastmoney_market_breadth | Tier B | 商业数据供应商（东方财富）全A快照公开接口，非交易所直发 |
| ths_limit_up_reveal | Tier B | 商业数据供应商（同花顺）公开页面 |
| tencent_quote | Tier B | 商业数据供应商（腾讯）公开行情接口 |
| mootdx_client | Tier C | 社区逆向通达信客户端协议的第三方库 |
| a_stock_data_wrapper | 包装层 | 不是独立来源，是对上述来源的封装 |

### 4.3 Tier A 核心来源

```text
Slice 1 Tier A core source: none
```

所有短线事实指标均依赖 Tier B 来源，无交易所/监管机构直发数据。这是本审计的核心风险之一。

---

## 5. Source-by-Source Evidence

### 5.1 Eastmoney push2ex（涨停板四池）

```text
source_id: eastmoney_limit_pool
source_name: 东方财富涨停板四池
tier: B
authority: 商业数据供应商，非交易所直发
official_documentation_or_entry: unclear（无公开 API 文档，端点为逆向页面接口）
underlying_source: unclear（东财聚合，未公开原始来源链路）
authentication: 无 API Key
request_method: GET
response_format: JSON
available_fields: c(代码), n(名称), lbc(连板数), fbt(首次封板时间), hybk(行业), zdp(涨跌幅), fund(封单资金), zttj(炸板统计)
trade_date_field: date(请求参数 YYYYMMDD)
source_updated_at_field: unclear（响应无显式 updated_at 字段）
intraday_semantics: 盘中动态更新，涨停池随封板/炸板实时变化
final_semantics: 收盘后池为当日最终集合，但来源未显式标记 is_final
history_depth: 可按 date 参数请求历史交易日
rate_limit: 社区实测 >5 次/秒、并发 ≥10、1 分钟 ≥200 次触发风控
stability: 间歇风控（HTTP 000 / 空响应 / 403）
licensing_status: unclear
cache_status: unclear
persistence_status: unclear
ui_display_status: unclear
redistribution_status: unclear
anti_bot_or_failure_behavior: 存在限流、空响应或访问控制风险；具体策略 not verified
recommended_use: 涨停/炸板/跌停/昨涨停数量与连板梯队
verification_status: reviewer-provided evidence, not independently reverified by Q
```

### 5.2 Eastmoney push2（全 A 快照）

```text
source_id: eastmoney_market_breadth
source_name: 东方财富全 A 快照
tier: B
authority: 商业数据供应商，非交易所直发
official_documentation_or_entry: unclear
underlying_source: unclear
authentication: 无 API Key
request_method: GET
response_format: JSON
available_fields: 代码, 名称, 涨跌幅, 成交额, 换手率, 总市值, 流通市值
trade_date_field: 隐含（按请求时点返回当日或最近交易日）
source_updated_at_field: unclear
intraday_semantics: 盘中实时刷新
final_semantics: 收盘后为当日最终值，来源未显式标记 is_final
history_depth: unclear
rate_limit: 同 push2ex
stability: 同 push2ex
licensing_status: unclear
cache_status: unclear
persistence_status: unclear
ui_display_status: unclear
redistribution_status: unclear
anti_bot_or_failure_behavior: 存在限流、空响应或访问控制风险；具体策略 not verified
recommended_use: 市场宽度（涨跌家数、成交额）
verification_status: reviewer-provided evidence, not independently reverified by Q
```

### 5.3 THS 10jqka（同花顺涨停揭秘）

```text
source_id: ths_limit_up_reveal
source_name: 同花顺涨停揭秘
tier: B
authority: 商业数据供应商，非交易所直发
official_documentation_or_entry: unclear（公开页面 data.10jqka.com.cn/dataapi/limit_up/limit_up_pool）
underlying_source: unclear
authentication: 无 API Key
request_method: GET
response_format: JSON
available_fields: 代码, 名称, reason_type(涨停原因), limit_up_type(板型), limit_up_suc_rate(封板成功率), open_num(开板次数), high_days(连板高度), first_limit_up_time, is_again_limit
trade_date_field: date(请求参数 YYYYMMDD)
source_updated_at_field: unclear
intraday_semantics: 盘中动态更新
final_semantics: 收盘后为当日最终集合，来源未显式标记 is_final
history_depth: 可按 date 参数请求历史
rate_limit: unclear（未公开阈值）
stability: unclear
licensing_status: unclear
cache_status: unclear
persistence_status: unclear
ui_display_status: unclear
redistribution_status: unclear
anti_bot_or_failure_behavior: 存在限流、空响应或访问控制风险；具体策略 not verified
recommended_use: 题材归因增强（非涨停数硬交叉源，含 ST 口径差异）
verification_status: not verified（Q 未本轮机械验证）
```

### 5.4 Tencent qt.gtimg.cn

```text
source_id: tencent_quote
source_name: 腾讯财经行情
tier: B
authority: 商业数据供应商
official_documentation_or_entry: unclear
underlying_source: unclear
authentication: 无 API Key
request_method: GET
response_format: GBK 文本
available_fields: 实时价、PE、PB、市值、换手率、涨跌停价、指数、ETF
trade_date_field: 隐含
source_updated_at_field: unclear
intraday_semantics: 盘中实时
final_semantics: 收盘后最终值，来源未显式标记 is_final
history_depth: 无涨停板池能力
rate_limit: unclear
stability: unclear
licensing_status: unclear
cache_status: unclear
persistence_status: unclear
ui_display_status: unclear
redistribution_status: unclear
anti_bot_or_failure_behavior: 存在限流、空响应或访问控制风险；具体策略 not verified
recommended_use: 个股行情校验，不提供全市场统计或涨停池
verification_status: not verified
```

### 5.5 mootdx

```text
source_id: mootdx_client
source_name: 通达信协议社区库
tier: C
authority: 社区逆向客户端，非官方
official_documentation_or_entry: 无官方文档
underlying_source: 通达信服务端协议
authentication: 无
request_method: TCP 7709 二进制
response_format: 二进制
available_fields: K线、五档盘口、逐笔成交、财务快照、F10
trade_date_field: 隐含
source_updated_at_field: unclear
intraday_semantics: 盘中实时
final_semantics: unclear
history_depth: K线历史
rate_limit: unclear
stability: 服务器 IP 老化，海外不可达
licensing_status: unclear
cache_status: unclear
persistence_status: unclear
ui_display_status: unclear
redistribution_status: unclear
anti_bot_or_failure_behavior: 存在限流、空响应或访问控制风险；具体策略 not verified
recommended_use: 不作为短线事实源（无涨停板池）
verification_status: not verified
```

---

## 6. Trading Calendar and Session Contract

### 6.1 时区

```text
timezone: Asia/Shanghai
```

### 6.2 场次定义

| 场次 | 时间（CST） | 数据状态 | session 值 |
|------|------------|---------|-----------|
| 盘前 | < 09:15 | 上一交易日 final 数据 | pre_open |
| 集合竞价 | 09:15–09:25 | 竞价数据，非连续 | call_auction |
| 开盘集合 | 09:25–09:30 | 当日开盘前 | call_auction |
| 上午连续 | 09:30–11:30 | 当日实时 | morning_session |
| 午间休市 | 11:30–13:00 | 上午最终值 | midday_break |
| 下午连续 | 13:00–14:57 | 当日实时 | afternoon_session |
| 收盘集合 | 14:57–15:00 | 收盘竞价 | close_pending |
| 收盘待定 | >= 15:00 | 当日数据但未确认稳定 | close_pending |
| 最终 | 来源日期正确 + 必需字段完整 + 连续稳定窗口满足 | 当日最终 | final |
| 不可用 | 数据源不可达或非交易日 | 无数据 | unavailable |

### 6.3 保守 final 判定

```text
不得将 >=15:00 直接定义为 final。
15:00 后进入 close_pending。
只有以下条件全部满足才进入 final：
  - 来源返回的 trade_date 与请求日期一致
  - 必需字段完整（非 null、非 upstream_null）
  - 连续稳定窗口满足（建议值：连续 2 次拉取结果一致，间隔 >= 60s）
无法确认时继续 close_pending 或 partial。
稳定窗口为建议值，不能冒充来源保证。
```

### 6.4 契约化字段

```text
trade_date: str (YYYY-MM-DD) — 来源返回的数据所属交易日
source_updated_at: str (ISO 8601 UTC) — 来源侧数据更新时间，unclear 时为 null
fetched_at: str (ISO 8601 UTC) — 本地实际拉取时间
snapshot_at: str (ISO 8601 UTC) — 快照生效时间
session: str — 上述场次值之一
is_final: bool — 是否进入 final
```

---

## 7. Market Universe Contract

### 7.1 Universe 定义

```text
breadth_universe: 用于市场宽度计算的股票集合
limit_pool_universe: 用于涨跌停池计算的股票集合
final_metric_universe: 用于最终指标输出的股票集合
```

### 7.2 逐项处理

| 板块/状态 | breadth_universe | limit_pool_universe | final_metric_universe | 说明 |
|-----------|-----------------|--------------------|-----------------------|------|
| SH main | included | included | included | 沪市主板 |
| SZ main | included | included | included | 深市主板（中小板已并入主板，不作独立市场） |
| ChiNext | included | included | included | 创业板 |
| STAR | included | included | included | 科创板 |
| BSE | excluded | excluded | excluded | 北交所 8 开头 |
| ST | included | included | included | 涨跌幅 5%，东财池按实际涨停价入池 |
| *ST | included | included | included | 退市风险警示，同 ST |
| IPO no-limit period | excluded | excluded | excluded | 新股上市前 5 日无涨跌幅限制，不进涨停池 |
| suspended | counted | excluded | excluded | 停牌计入 eligible_count 但不计入 valid_count |
| resumed | included | included | included | 复牌首日若无涨跌幅限制则 excluded |
| delisting period | excluded | excluded | excluded | 退市整理期 |
| B shares | excluded | excluded | excluded | 本项目不覆盖 |
| ETF | excluded | excluded | excluded | 非个股 |
| LOF | excluded | excluded | excluded | 非个股 |
| convertible bonds | excluded | excluded | excluded | 非个股 |
| funds | excluded | excluded | excluded | 非个股 |
| indexes | excluded | excluded | excluded | 非个股 |

### 7.3 市场宽度计数

```text
eligible_count: breadth_universe 中的总股票数（含停牌）
valid_count: eligible_count - suspended_count（有有效涨跌幅的股票）
suspended_count: 停牌股票数
advance_count + decline_count + flat_count + suspended_count = eligible_count
advance_count + decline_count + flat_count = valid_count
```

---

## 8. Metric Contract Matrix

每个指标具备完整 16 字段合同。未验证项标 `unclear` / `not verified`。不得使用"同上/见前文/按通用规则/N/A"等模糊值，除非字段确实不适用并写明原因。

### 8.1 市场宽度指标

```text
metric_id: advance_count
definition: 当日上涨股票数
unit: 股
numerator: valid_count 中 change_pct > 0 的股票数
denominator: not applicable; 计数指标，非比率
universe: breadth_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final（盘中可初步计算，收盘后稳定）
source_fields: 全A快照 change_pct（东财 push2 字段 f3）
formula: count(change_pct > 0)
missing_semantics: null（不缺失）
partial_condition: valid_count 覆盖率不足时 status=partial
unavailable_condition: 快照 transport 失败时 null
limitations: 单源（东财），无交叉验证
slice: 1
decision: GO
```

```text
metric_id: decline_count
definition: 当日下跌股票数
unit: 股
numerator: valid_count 中 change_pct < 0 的股票数
denominator: not applicable; 计数指标，非比率
universe: breadth_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 全A快照 change_pct（东财 push2 字段 f3）
formula: count(change_pct < 0)
missing_semantics: null
partial_condition: valid_count 覆盖率不足时 status=partial
unavailable_condition: 快照 transport 失败时 null
limitations: 单源（东财）
slice: 1
decision: GO
```

```text
metric_id: flat_count
definition: 当日平盘股票数
unit: 股
numerator: valid_count 中 change_pct == 0 的股票数
denominator: not applicable; 计数指标，非比率
universe: breadth_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 全A快照 change_pct（东财 push2 字段 f3）
formula: count(change_pct == 0)
missing_semantics: null
partial_condition: valid_count 覆盖率不足时 status=partial
unavailable_condition: 快照 transport 失败时 null
limitations: 单源（东财）
slice: 1
decision: GO
```

```text
metric_id: suspended_count
definition: 当日停牌股票数
unit: 股
numerator: eligible_count 中无有效涨跌幅的股票数
denominator: not applicable; 计数指标，非比率
universe: breadth_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 全A快照 停牌标记（东财 push2 字段，候选 semantics not verified）
formula: eligible_count - valid_count
missing_semantics: null
partial_condition: valid_count 覆盖率不足时 status=partial
unavailable_condition: 快照 transport 失败时 null
limitations: 单源（东财）；停牌标记字段 semantics not verified
slice: 1
decision: GO
```

```text
metric_id: eligible_count
definition: breadth_universe 总股票数
unit: 股
numerator: not applicable; 计数指标，非比率
denominator: not applicable; 计数指标，非比率
universe: breadth_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 全A快照 股票代码列表（东财 push2 字段 f12）
formula: count(breadth_universe)
missing_semantics: null
partial_condition: valid_count 覆盖率不足时 status=partial
unavailable_condition: 快照 transport 失败时 null
limitations: 单源（东财）
slice: 1
decision: GO
```

### 8.2 涨跌停指标

```text
metric_id: limit_up_count
definition: 当日涨停股票数（收盘封板）
unit: 股
numerator: limit_pool_universe 中 zt_pool 的股票数
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final（盘中动态变化，final 为稳定值）
source_fields: 东财 push2ex getTopicZTPool 返回的 pool 数组
formula: len(zt_pool)
missing_semantics: null
partial_condition: transport 成功但 trade_date 不匹配时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 单源（东财），zt_pool 是否为收盘封板 not independently verified
slice: 1
decision: GO
```

```text
metric_id: limit_down_count
definition: 当日跌停股票数
unit: 股
numerator: limit_pool_universe 中 dt_pool 的股票数
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicDTPool 返回的 pool 数组
formula: len(dt_pool)
missing_semantics: null
partial_condition: transport 成功但 trade_date 不匹配时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 单源（东财）
slice: 1
decision: GO
```

```text
metric_id: touched_limit_up_count
definition: 当日触及涨停的股票数（封板 + 炸板）
unit: 股
numerator: limit_up_count + failed_limit_up_count
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool + getTopicZBPool 返回的 pool 数组
formula: len(zt_pool) + len(zb_pool)
missing_semantics: null
partial_condition: transport 成功但 zt/zb 任一缺失时 null
unavailable_condition: 池 transport 失败时 null
limitations: zt_pool 与 zb_pool 是否互斥 not independently verified；二者之和是否等于 touched_limit_up_count not independently verified
slice: 1
decision: CONDITIONAL GO
```

```text
metric_id: touched_limit_down_count
definition: 盘中曾触及跌停价的证券数量
unit: 股
numerator: 触及跌停的唯一证券数
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 候选跌停池/触及跌停字段（东财 push2ex），当前未机械确认；semantics not verified
formula: count(触及跌停价)
missing_semantics: 候选字段未确认时 null
partial_condition: transport 成功但字段缺失时 null
unavailable_condition: 池 transport 失败时 null
limitations: 现有来源无法明确区分收盘跌停与盘中触及跌停后打开；semantics not independently verified
slice: 1
decision: NO-GO
```

```text
metric_id: failed_limit_up_count
definition: 当日炸板股票数（触涨停后开板）
unit: 股
numerator: limit_pool_universe 中 zb_pool 的股票数
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZBPool 返回的 pool 数组
formula: len(zb_pool)
missing_semantics: null
partial_condition: transport 成功但 trade_date 不匹配时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 单源（东财）；zb_pool 语义（触板未封）not independently verified
slice: 1
decision: GO
```

```text
metric_id: failed_board_rate
definition: 炸板率
unit: ratio [0,1]
numerator: failed_limit_up_count
denominator: limit_up_count + failed_limit_up_count
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool + getTopicZBPool 返回的 pool 数组
formula: zb_count / (zt_count + zb_count)
missing_semantics: 分母为 0 时 null（合法零值）
partial_condition: 分母为 0 时 null（合法零值）
unavailable_condition: 池 transport 失败时 null
limitations: 单源；zt/zb 互斥性未验证
slice: 1
decision: GO
```

```text
metric_id: sealed_limit_up_count
definition: 当日封板涨停股票数
unit: 股
numerator: limit_up_count
denominator: not applicable; 计数指标，非比率
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool 返回的 pool 数组
formula: len(zt_pool)
missing_semantics: null
partial_condition: transport 成功但 trade_date 不匹配时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 等同 limit_up_count；seal quality 完整定义见 §8.6
slice: 1
decision: GO
```

```text
metric_id: seal_rate
definition: 封板率
unit: ratio [0,1]
numerator: sealed_limit_up_count
denominator: limit_up_count + failed_limit_up_count
universe: limit_pool_universe
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool + getTopicZBPool 返回的 pool 数组
formula: zt_count / (zt_count + zb_count)
missing_semantics: 分母为 0 时 null（合法零值）
partial_condition: 分母为 0 时 null（合法零值）
unavailable_condition: 池 transport 失败时 null
limitations: 不等同于完整封板质量（见 §8.6）
slice: 1
decision: GO
```

### 8.3 连板与梯队

```text
metric_id: consecutive_limit_up_days
definition: 涨停股连板天数
unit: 日
numerator: not applicable; 每股属性，非聚合比率
denominator: not applicable; 每股属性，非聚合比率
universe: zt_pool
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool 字段 lbc（连板数）
formula: zt_pool 各股 lbc 值
missing_semantics: lbc 为 null 时该股排除
partial_condition: transport 成功但 lbc 字段缺失时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 单源（东财）
slice: 2
decision: GO
```

```text
metric_id: ladder
definition: 连板梯队
unit: list[{boards, count}]
numerator: not applicable; 分档计数，非比率
denominator: not applicable; 分档计数，非比率
universe: zt_pool
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool 字段 lbc
formula: 按 lbc 分档计数
missing_semantics: lbc 为 null 排除
partial_condition: transport 成功但 lbc 字段缺失时 partial
unavailable_condition: 池 transport 失败时 null
limitations: 单源（东财）
slice: 2
decision: GO
```

```text
metric_id: layered_promotion_rates
definition: 分层晋级率（不得再用"今日二板及以上/昨日全部涨停"作为完整晋级率）
unit: list[{from_level, to_level, numerator, denominator, sample_count, rate}]
numerator: 昨日 N 板中今日 N+1 板的股票数（跨日身份匹配）
denominator: 昨日 N 板股票数
universe: zt_pool(今日) + yzt_pool(昨日)
trade_date: current_trade_date + previous_trade_date（当前 + 前一交易日组合）
session: final only（需今日 final + 昨日 final 跨日匹配）
source_fields: 东财 push2ex getTopicZTPool 字段 lbc + getYesterdayZTPool 字段 lbc（跨日身份匹配）
formula: 分层转换，昨日首板→今日二板、昨日二板→今日三板、昨日三板→今日四板...
missing_semantics: 分母为 0 时该层 null
partial_condition: 跨日匹配未完成时 null
unavailable_condition: 昨涨停池 transport 失败时 null
limitations: 跨日股票身份匹配尚未机械验证
slice: 2
decision: CONDITIONAL GO
```

### 8.4 溢价与亏钱效应

```text
metric_id: next_open_return
definition: 昨涨停股次日开盘收益率
unit: ratio
numerator: 次日开盘价 - baseline_price
denominator: baseline_price
universe: yzt_pool
trade_date: T+1 trade_date（次日交易日）
session: final only（需次日 final 开盘价）
source_fields: unclear（来源未提供明确的次日开盘字段）
formula: (next_open - baseline) / baseline
missing_semantics: null
partial_condition: null
unavailable_condition: 来源字段未确认，无法计算
limitations: baseline_price 定义 unclear；adjustment_method unclear；suspension_handling unclear；one_price_limit_handling unclear；outlier_handling unclear；来源字段未确认
slice: 2
decision: NO-GO as currently specified
```

```text
metric_id: next_close_return
definition: 昨涨停股次日收盘收益率
unit: ratio
numerator: 次日收盘价 - baseline_price
denominator: baseline_price
universe: yzt_pool
trade_date: T+1 trade_date（次日交易日）
session: final only（需次日 final 收盘价）
source_fields: zdp（候选，semantics not verified）
formula: (next_close - baseline) / baseline
missing_semantics: null
partial_condition: zdp 语义未确认时 null
unavailable_condition: 来源字段不可达时 null
limitations: zdp 语义未确认；baseline_price unclear；adjustment_method unclear；suspension_handling unclear；one_price_limit_handling unclear；outlier_handling unclear
slice: 2
decision: CONDITIONAL GO
```

```text
metric_id: next_high_return
definition: 昨涨停股次日最高价收益率
unit: ratio
numerator: 次日最高价 - baseline_price
denominator: baseline_price
universe: yzt_pool
trade_date: T+1 trade_date（次日交易日）
session: final only（需次日 final 最高价）
source_fields: unclear（来源未提供明确的次日最高价字段）
formula: (next_high - baseline) / baseline
missing_semantics: null
partial_condition: null
unavailable_condition: 来源字段未确认，无法计算
limitations: baseline_price unclear；adjustment_method unclear；suspension_handling unclear；one_price_limit_handling unclear；outlier_handling unclear；来源字段未确认
slice: 2
decision: NO-GO as currently specified
```

```text
metric_id: loss_effect
definition: 亏钱效应（最小定义：昨日涨停股次日收益分布）
unit: ratio
numerator: yzt_pool 中次日收益 < 0 的股票数
denominator: yzt_pool 总数
universe: yzt_pool
trade_date: T+1 trade_date（次日交易日）
session: final only（需次日 final 收益数据）
source_fields: zdp（候选，semantics not verified）
formula: count(return < 0) / len(yzt_pool)
missing_semantics: 分母为 0 时 null
partial_condition: zdp 语义未确认时 null
unavailable_condition: 来源字段不可达时 null
limitations: 最小定义仅代表"昨日涨停股次日下跌比例"，不代表完整亏钱效应（应含次日平均收益、中位收益、炸板股次日收益、最高连板股次日收益、跌停数量、大跌数量、高位股回撤，但这些均未验证）
slice: 2
decision: CONDITIONAL GO
```

### 8.5 题材结构

```text
metric_id: theme_structure
definition: 题材结构（题材聚合容器）
unit: list[theme]
numerator: not applicable; 聚合容器，非比率
denominator: not applicable; 聚合容器，非比率
universe: zt_pool
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: reason_type（THS，semantics not verified）, hybk（东财，semantics not verified）
formula: 按 reason_type/hybk 归类统计
missing_semantics: 来源不可用时 null
partial_condition: THS 不可用时 hybk 降级
unavailable_condition: 双源均不可用时 null
limitations: theme_name_source 归一化未审计；stock_theme_many_to_many 未审计；synonym_handling 未审计；duplicate_concepts 未审计；objective_mainline_rule 未定义；missing_source_semantics 未定义
slice: 2
decision: CONDITIONAL GO
```

```text
metric_id: theme_limit_up_count
definition: 题材内符合 limit_up_count 口径的唯一股票数
unit: 股
numerator: 题材内符合 limit_up_count 口径的唯一股票数
denominator: not applicable; 计数指标，非比率
universe: zt_pool（按题材过滤）
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: reason_type（THS）, hybk（东财）, 东财 push2ex getTopicZTPool pool 数组
formula: count(zt_pool 中属于该题材的股票)
missing_semantics: 题材映射不可用时 null
partial_condition: THS 不可用时 hybk 降级
unavailable_condition: 双源均不可用时 null
limitations: 题材归一化未审计；同义词处理未审计；重复概念未审计
slice: 2
decision: CONDITIONAL GO
```

```text
metric_id: theme_ladder_height
definition: 题材内最高 consecutive_limit_up_days
unit: 日
numerator: not applicable; 每题材属性，非比率
denominator: not applicable; 每题材属性，非比率
universe: zt_pool（按题材过滤）
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: 东财 push2ex getTopicZTPool 字段 lbc, reason_type（THS）, hybk（东财）
formula: max(题材内 zt_pool 各股 lbc)
missing_semantics: 题材映射不可用时 null
partial_condition: THS 不可用时 hybk 降级
unavailable_condition: 双源均不可用时 null
limitations: 题材归一化未审计；lbc 字段 semantics not independently verified
slice: 2
decision: CONDITIONAL GO
```

```text
metric_id: theme_stock_count
definition: 归一化题材映射后的唯一股票数
unit: 股
numerator: not applicable; 计数指标，非比率
denominator: not applicable; 计数指标，非比率
universe: zt_pool（按题材过滤）
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: reason_type（THS）, hybk（东财）, 东财 push2ex getTopicZTPool pool 数组
formula: count(归一化题材映射后的唯一股票)
missing_semantics: 题材映射不可用时 null
partial_condition: THS 不可用时 hybk 降级
unavailable_condition: 双源均不可用时 null
limitations: 题材归一化未审计；同义词处理未审计；重复概念未审计
slice: 2
decision: CONDITIONAL GO
```

```text
metric_id: theme_internal_breadth
definition: 题材内部上涨比例
unit: ratio [0,1]
numerator: 题材内上涨股票数
denominator: 题材内有效股票数
universe: zt_pool（按题材过滤）
trade_date: current_trade_date（当前快照交易日）
session: intraday_preliminary + close_pending + final
source_fields: reason_type（THS）, hybk（东财）, 全A快照 change_pct
formula: count(题材内 change_pct > 0) / count(题材内有效股票)
missing_semantics: 分母为 0 时 null
partial_condition: 题材映射不可用时 null
unavailable_condition: 双源均不可用时 null
limitations: 题材归一化未审计；同义词处理未审计；重复概念未审计
slice: 2
decision: CONDITIONAL GO
```

### 8.6 Seal Quality 字段审计

供应商池定义是否经过独立验证：

```text
zt_pool 是否为收盘封板: not independently verified
zb_pool 是否为触板未封: not independently verified
二者是否互斥: not independently verified
二者之和是否等于 touched_limit_up_count: not independently verified
decision: CONDITIONAL GO
```

seal_rate 不等同于完整封板质量。逐字段审计：

| 字段 | 来源 | decision | 依据 |
|------|------|---------|------|
| first_limit_up_time | 东财 fbt | GO | 字段存在 |
| last_limit_up_time | unclear | NO-GO | 来源未确认 |
| open_count（开板次数） | 东财 zttj / THS open_num | CONDITIONAL GO | 字段存在但语义未独立验证 |
| seal_amount（封单金额） | 东财 fund | CONDITIONAL GO | 字段存在但未验证 |
| seal_volume（封单量） | unclear | NO-GO | 来源未确认 |
| seal_ratio（封单比） | unclear | NO-GO | 需计算，来源字段不全 |
| turnover（换手率） | 全A快照 | GO | 字段存在 |
| float_market_cap（流通市值） | 全A快照 | GO | 字段存在 |

### 8.7 Premium 与 Loss Effect 详细定义

premium 不得使用不存在的 `pct` 字段。C 发现的候选字段为 `zdp`，但语义未确认前不得直接计算。

```text
next_open_return:
  baseline_price: unclear（昨日收盘价 vs 涨停价，未确认）
  adjustment_method: unclear
  sample_universe: yzt_pool
  suspension_handling: unclear
  one_price_limit_handling: unclear
  outlier_handling: unclear
  decision: NO-GO as currently specified

next_close_return:
  baseline_price: unclear
  source_fields: zdp（候选，语义未确认）
  adjustment_method: unclear
  suspension_handling: unclear
  one_price_limit_handling: unclear
  outlier_handling: unclear
  decision: CONDITIONAL GO

next_high_return:
  source_fields: unclear
  decision: NO-GO as currently specified
```

loss_effect 完整定义应比较（均未验证）：

```text
- 昨日涨停股次日平均收益
- 昨日涨停股次日中位收益
- 昨日炸板股次日收益
- 最高连板股次日收益
- 跌停数量
- 大跌数量
- 高位股回撤
最小定义（昨日涨停股次日下跌比例）仅代表该比例，不代表完整亏钱效应。
```

---

## 9. Exact Numerators and Denominators

| metric_id | numerator | denominator | 分母为 0 时 |
|-----------|-----------|-------------|-----------|
| advance_count | count(change_pct>0) | not applicable | — |
| decline_count | count(change_pct<0) | not applicable | — |
| flat_count | count(change_pct==0) | not applicable | — |
| suspended_count | eligible - valid | not applicable | — |
| eligible_count | count(breadth_universe) | not applicable | — |
| limit_up_count | len(zt_pool) | not applicable | — |
| limit_down_count | len(dt_pool) | not applicable | — |
| touched_limit_up_count | len(zt_pool)+len(zb_pool) | not applicable | — |
| touched_limit_down_count | count(触及跌停价) | not applicable | — |
| failed_limit_up_count | len(zb_pool) | not applicable | — |
| failed_board_rate | failed_limit_up_count | limit_up_count + failed_limit_up_count | null（合法零值） |
| sealed_limit_up_count | len(zt_pool) | not applicable | — |
| seal_rate | sealed_limit_up_count | limit_up_count + failed_limit_up_count | null（合法零值） |
| up_ratio | advance_count | valid_count | null |
| layered_promotion_rates | 昨日N板→今日N+1板匹配数 | 昨日N板总数 | null |
| next_open_return | 次日开盘价 - baseline_price | baseline_price | null |
| next_close_return | 次日收盘价 - baseline_price | baseline_price | null |
| next_high_return | 次日最高价 - baseline_price | baseline_price | null |
| loss_effect | count(return<0) | len(yzt_pool) | null |
| theme_limit_up_count | 题材内涨停股票数 | not applicable | — |
| theme_ladder_height | not applicable | not applicable | — |
| theme_stock_count | not applicable | not applicable | — |
| theme_internal_breadth | 题材内上涨股票数 | 题材内有效股票数 | null |

---

## 10. Three-Date Cross-Source Verification

### 10.1 C 复审基准值

以下数值为 C 复审提供，Q 未本轮独立机械验证：

| 日期 | 指标 | C 复审值 | verification_status |
|------|------|---------|-------------------|
| 2026-07-28 | zt | 61 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-28 | zb | 20 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-28 | dt | 49 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-29 | zt | 81 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-29 | zb | 14 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-29 | dt | 9 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-30 | zt | 52 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-30 | zb | 19 | reviewer-provided evidence, not independently reverified by Q |
| 2026-07-30 | dt | 74 | reviewer-provided evidence, not independently reverified by Q |

### 10.2 每行验证元数据

```text
source_id: eastmoney_limit_pool
endpoint: push2ex.eastmoney.com/{getTopicZTPool|getTopicZBPool|getTopicDTPool}
checked_at: not verified by Q（C 复审提供）
fetched_at: not verified by Q
verification_status: reviewer-provided evidence, not independently reverified by Q
limitations: Q 未本轮重新拉取东财接口验证；数值来自 C 复审
```

### 10.3 同花顺交叉验证

```text
THS numeric comparison: not verified
```

Q 本轮未实际机械验证同花顺涨停揭秘三日数值。不得写 `< 5%` 等偏差结论，除非三个日期均有两源具体数值可复算。

### 10.4 单源声明

```text
zt/zb/dt: single-source (eastmoney push2ex), not cross-validated
breadth (up_count/down_count): single-source (eastmoney push2), not cross-validated
Tencent 提供个股涨跌幅但不提供全市场统计，不构成独立交叉源
```

---

## 11. Licensing and Display Boundaries

### 11.1 许可状态

| 来源 | licensing_status | cache_status | persistence_status | ui_display_status | redistribution_status |
|------|-----------------|-------------|-------------------|-------------------|----------------------|
| Eastmoney push2/push2ex | unclear | unclear | unclear | unclear | unclear |
| THS 10jqka | unclear | unclear | unclear | unclear | unclear |
| Tencent qt.gtimg.cn | unclear | unclear | unclear | unclear | unclear |
| mootdx | unclear | unclear | unclear | unclear | unclear |

### 11.2 删除的无证据断言

以下结论无正式条款证据，已删除或改为 unclear：

```text
- "无许可风险" → deleted
- "个人研究用途允许" → deleted
- "公开接口可以使用" → deleted
- "不得商用再分发" → deleted（无依据时不得做任何方向断言）
- "腾讯不封 IP" → deleted
```

### 11.3 明确声明

```text
无需 API Key 只表示访问方式，不代表许可。
所有来源许可均为 unclear。
整体 CONDITIONAL GO 必须把许可不明确列为进入 Slice 1 的约束。
仅用于受控研究环境。
```

---

## 12. Cache and Snapshot Strategy

### 12.1 缓存键

```text
cache_key = source_id + trade_date + session + schema_version
```

### 12.2 快照字段区分

```text
requested_date: 用户请求的日期
trade_date: 来源返回的数据所属交易日
cache_trade_date: 缓存版本对应的 trade_date
fetched_at: 本地实际拉取时间
source_updated_at: 来源侧更新时间（unclear 时 null）
snapshot_at: 快照生效时间
```

### 12.3 缓存规则

```text
- 只有 is_final=true 的版本化快照可以长期缓存
- 来源修订必须产生新快照版本
- 所有缓存保留 provenance（source_id / trade_date / fetched_at / snapshot_at）
- 不得写"收盘后 TTL 无限"
- 非交易日返回最近交易日时，必须明确不是今日数据（session=pre_open, trade_date=最近交易日）
```

### 12.4 盘中 TTL

```text
盘中 TTL: 300 秒（建议值）
空结果不缓存（下次请求重试）
```

---

## 13. Data Health Mapping

### 13.1 新增 source_id

| source_id | module | display_name | stale_after_seconds |
|-----------|--------|-------------|-------------------|
| `eastmoney_limit_pool` | market | 东财涨停板池 | 600 |
| `eastmoney_market_breadth` | market | 东财全A市场广度 | 600 |

### 13.2 合法零值处理

合法的 0 涨停、0 炸板、0 跌停不得自动视为 partial。必须区分：

```text
transport_success: HTTP 请求是否成功
parse_success: JSON 是否可解析
required_field_present: 必需字段是否存在
data_array_present: 数据数组是否存在
trade_date_match: trade_date 是否与请求日期一致
row_count: 返回行数
legal_zero: 合法零值（0 涨停等，交易日无涨停是合法的）
upstream_null: 只有 transport_success=true、parse_success=true，且上游明确返回 null 时才为 true。transport 失败时 upstream_null=false。不得将"没有收到响应"解释为"上游返回 null"。
unexplained_empty: 无法解释的空
```

### 13.3 状态判定

```text
normal: transport_success + parse_success + required_field_present + trade_date_match
  （row_count 可为 0，即 legal_zero）
partial: 数据存在但覆盖率不足或部分字段缺失
unavailable: transport 失败 或 parse 失败 或 upstream_null 或 unexplained_empty
```

### 13.4 Data Health 定义

```text
required_fields: [trade_date, session, is_final, source_id]
completeness_checks: required_field_present
semantic_checks: trade_date_match, row_count
normal_conditions: 上述全满足
partial_conditions: 数据存在但覆盖率不足
unavailable_conditions: transport/parse 失败
limitations: 单源，无法自动发现数据错误
```

### 13.5 删除固定阈值

删除永久固定规则 `valid_count >= 4000`。改为候选检查（均标为 proposal）：

```text
coverage_ratio: valid_count / eligible_count（proposal, 阈值待验证）
与 eligible_count 比较（proposal）
与最近 final 快照比较（proposal）
按市场分区检查（proposal）
```

---

## 14. Preflight Sufficiency Rules

### 14.1 规则定义

| 规则 ID | 条件 | 不满足时 |
|---------|------|---------|
| PF-01 | data_trade_date 为有效交易日 | status = unavailable |
| PF-02 | 全 A 快照 valid_count 覆盖率达标（proposal） | status = partial, warning |
| PF-03 | 涨停池 transport_success + data_array_present（非 upstream_null） | transport 失败 → unavailable；data_array 缺失 → partial, warning |
| PF-04 | 涨停池 + 炸板池至少一个 data_array_present | break_rate = null |
| PF-05 | 昨涨停池非空（计算晋级率时） | promotion_rate = null |
| PF-06 | observed_at 与当前时间差 < stale_after_seconds | is_stale = True |

### 14.2 合法零值

```text
PF-03/PF-04 不得以"池非空"判断接口成功。
池为空但 transport_success + data_array_present + trade_date_match 时仍为 normal。
row_count=0 是 legal_zero，不是 partial。
```

### 14.3 降级语义

```text
normal: PF-01 ~ PF-03 全部满足（row_count 可为 0）
partial: PF-01 满足，transport 成功 + 解析成功 + 核心身份字段存在，但可选字段缺失或覆盖率不足
unavailable: PF-01 不满足，或 transport 失败，或 parse 失败，或 upstream_null，或 unexplained_empty
```

transport 失败必须为 unavailable，不得为 partial。只有 transport 成功、解析成功、核心身份字段存在但可选字段缺失或覆盖率不足时才可为 partial。

---

## 15. Offline Fixture Contract

配套文件：`docs/research/BK11_SHORT_TERM_FACTS_FIXTURE_V01.json`

### 15.1 结构

```json
{
  "schema_version": "bk11-short-term-facts-fixture.v0.1",
  "fixture_kind": "synthetic-normalized",
  "generated_at": "<ISO 8601 UTC>",
  "trade_dates": ["<YYYY-MM-DD>", ...],
  "cases": [
    {"case_id": "normal", ...},
    {"case_id": "partial", ...},
    {"case_id": "unavailable", ...}
  ]
}
```

### 15.2 每个 case 必需字段

```text
case_id, status, trade_date, session, is_final, source_ids, fetched_at,
snapshot_at, universe, breadth, limit_activity, data_health, limitations,
reason_codes, missing_fields, unavailable_metrics
```

### 15.3 字段映射

Fixture 统一字段名，不混用旧字段名：

| 旧字段 | 新字段 |
|--------|--------|
| data_trade_date | trade_date |
| observed_at | snapshot_at |
| source_id | source_ids |
| market_breadth | breadth |
| limit_pool | limit_activity |

### 15.4 用途

```text
Slice 1+ 的单元测试使用 fixture 中 cases 数组。
不依赖网络即可验证指标计算、降级逻辑、Preflight 规则。
fixture 中的数字为手动构造的合成值，仅用于测试 schema 和计算一致性，
不代表实际历史市场数据。
```

### 15.5 Unavailable case 约束

```text
不得携带事实指标（breadth=null, limit_activity=null）
必须有 reason_codes
不得包含 TimeoutError 等内部异常文本
```

---

## 16. Per-Metric Go/Conditional Go/No-Go

| 指标 | decision | 依据 |
|------|---------|------|
| breadth (advance/decline/flat/suspended/eligible) | GO | 全A快照已实现，纯计算 |
| limit up count | GO | 涨停池已实现 |
| limit down count | GO | 跌停池已实现 |
| touched limit up | CONDITIONAL GO | zt/zb 互斥性未独立验证 |
| touched limit down | NO-GO | 现有来源无法区分收盘跌停与盘中触及跌停 |
| failed boards (zb) | GO | 炸板池已实现 |
| seal quality | NO-GO | 完整封板质量未定义（seal_rate 仅基础比例） |
| ladder | GO | 涨停池 lbc 已实现 |
| promotion | CONDITIONAL GO | 跨日身份匹配未机械验证 |
| premium (next_open/next_high) | NO-GO as currently specified | 来源字段未确认，baseline unclear |
| premium (next_close) | CONDITIONAL GO | zdp 候选语义未确认 |
| loss effect | CONDITIONAL GO | 最小定义可计算，完整定义未验证 |
| theme_structure | CONDITIONAL GO | 归一化未审计 |
| theme_limit_up_count | CONDITIONAL GO | 题材归一化未审计 |
| theme_ladder_height | CONDITIONAL GO | 题材归一化未审计 |
| theme_stock_count | CONDITIONAL GO | 题材归一化未审计 |
| theme_internal_breadth | CONDITIONAL GO | 题材归一化未审计 |
| intraday | CONDITIONAL GO | 盘中数据动态变化，需 session 标记 |
| final | CONDITIONAL GO | final 判定为保守合同，稳定窗口为建议值 |
| history | NO-GO | 历史回补未审计（Slice 4） |
| T+1 | NO-GO | T+1 闭环未验证（Slice 4） |

---

## 17. Overall Decision

### CONDITIONAL GO

理由：

1. Slice 1 核心指标（市场宽度 + 涨跌停 + 炸板 + 基础 break/seal）数据源已实现。
2. Tier A 核心来源缺失，所有数据均来自 Tier B/C，许可 unclear。
3. 单源无交叉验证，数据错误无法自动发现。
4. final 判定为保守合同，稳定窗口为建议值。
5. 合法零值需响应状态区分。

### Slice 1 允许范围

```text
- 市场宽度（advance/decline/flat/suspended/eligible）
- 涨停数量
- 跌停数量
- 炸板数量
- 基础 break/seal 比例
```

### Slice 1 继续阻断

```text
- 错误总体晋级率（需分层转换）
- 未确认 premium
- 未定义 loss_effect（完整版）
- 完整 seal quality
- theme structure
- 历史回补
- T+1 闭环
```

---

## 18. Slice 1 Entry Conditions

```text
1. 本 Slice 0 审计文档已提交并推送。
2. 用户明确授权进入 Slice 1。
3. 许可仍为 unclear，仅用于受控研究环境。
4. 保留 provenance（source_id / trade_date / fetched_at / snapshot_at）。
5. Data Health 可降级，合法零值不判失败。
6. 不实现未通过指标。
7. Slice 1 范围：市场宽度 + 涨跌停 + 炸板 + 基础 break/seal。
8. Slice 1 必须：纯计算、无 LLM、统一 envelope、接入 Data Health、固定 fixture 测试。
9. Slice 1 不得：新建前端页面、修改 router/app、引入新依赖。
```

---

## 19. Limitations and Unverified Claims

```text
1. 来源许可 unclear：所有 Tier B/C 来源均无正式条款证据。
2. Tier A 核心来源缺失：无交易所/监管机构直发数据。
3. THS 三日数值未完整验证：Q 未本轮机械验证，标 not verified。
4. final 时点未验证：稳定窗口为建议值，来源未提供 is_final。
5. 合法零值需响应状态区分：0 涨停不得自动视为 partial。
6. 供应商池语义未独立确认：zt_pool 是否收盘封板、zb_pool 是否触板未封、二者互斥性、二者之和是否等于 touched_limit_up_count 均 not independently verified。
7. zdp 语义未确认：候选字段 zdp 的含义（今日涨幅 vs 次日收益）未确认。
8. 历史回补未审计：Slice 4 范围。
9. 题材归一化未审计：同义词、重复概念、主线条规则均未定义。
```

---

## 20. Evidence Log

| checked_at | source_id | entry_or_endpoint | action | trade_date | result | verification_status | limitations |
|-----------|-----------|-------------------|--------|-----------|--------|-------------------|------------|
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZTPool | 引用 C 复审值 | 2026-07-28 | zt=61 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZBPool | 引用 C 复审值 | 2026-07-28 | zb=20 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicDTPool | 引用 C 复审值 | 2026-07-28 | dt=49 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZTPool | 引用 C 复审值 | 2026-07-29 | zt=81 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZBPool | 引用 C 复审值 | 2026-07-29 | zb=14 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicDTPool | 引用 C 复审值 | 2026-07-29 | dt=9 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZTPool | 引用 C 复审值 | 2026-07-30 | zt=52 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicZBPool | 引用 C 复审值 | 2026-07-30 | zb=19 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | eastmoney_limit_pool | push2ex getTopicDTPool | 引用 C 复审值 | 2026-07-30 | dt=74 | reviewer-provided evidence, not independently reverified by Q | Q 未本轮拉取 |
| 2026-08-02 | ths_limit_up_reveal | dataapi limit_up_pool | 未验证 | 2026-07-28 | not verified | not verified | Q 未本轮拉取 |
| 2026-08-02 | ths_limit_up_reveal | dataapi limit_up_pool | 未验证 | 2026-07-29 | not verified | not verified | Q 未本轮拉取 |
| 2026-08-02 | ths_limit_up_reveal | dataapi limit_up_pool | 未验证 | 2026-07-30 | not verified | not verified | Q 未本轮拉取 |

---

## 附录 A：不处理事项

```text
AlertEvaluation 自约束
嵌套 dict 自动模型化
跨字段 technical_status/metrics 一致性
API router 实现
前端页面
通知/调度
求值历史
数据库迁移
LangGraph / 多 Agent
vibe-astock 仓库代码复制
```
