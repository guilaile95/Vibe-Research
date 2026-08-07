# BK-11 零成本数据源可行性探测 v0.1

| 项 | 值 |
|----|-----|
| 阶段 | bk11-free-source-feasibility-v0.1 |
| 分支 | research/bk11-free-source-feasibility-v0.1 |
| Base | cd17fec2cc28d8dd9ea9b8e37df0cc6c394a0b18（feature/research-system-v01） |
| 探测时间 | 2026-08-06 17:06–17:22 与 18:04–18:25 Asia/Shanghai（修复后复测） |
| 结果 | **FEASIBLE_ZERO_COST_PARTIAL** |

> 2026-08-07 合同关闭说明：`--max-requests` 只定义为 harness 可直接控制的
> K 线主探测/重试/determinism 请求硬上限；login/logout 与
> query_all_stock SDK 内部分页只做独立观测计数，不再宣称受同一硬预算控制。
> 显式 0/负数预算必须在 login 前拒绝。运行时 universe 与 K 线
> tradeStatus 均严格要求 `0/1`，determinism 一致性纳入 breadth identity。
> 本文件所有全市场性能口径统一使用最终成功实测：
> **577.66s / 约 9.6 分钟 / 9.0 req/s**。

## 一、结论摘要

```text
BaoStock（免费匿名）：历史股票池、历史单日行情、停牌状态、市场宽度全部可行；
  日期绑定明确（请求日回显 + 行内日期）；全市场单日 5204/5204 成功，
  总耗时 577.66s（约 9.6 分钟），9.0 req/s；breadth 恒等式成立。

东方财富指定日期停复牌接口：可用；与 BaoStock 停牌集合按“T 日处于停牌”
  口径完全一致（目标股票池 5/5），日期语义差异可解释。

东方财富涨停/跌停/炸板池：传输层可用且随日期参数变化；但响应内唯一
  日期字段 data.qdate 为“服务器查询日”而非“池所属交易日”，已批准适配器
  对历史日期请求失败关闭（TRADE_DATE_MISMATCH）→ 涨跌停活动只能进入
  partial；legal-zero 仍 NOT_PROVEN。

因此：advance/decline/flat/suspended/eligible 可可靠生成；整体日事实
  不允许标记 normal（涨跌停活动日期绑定未证明）。
```

## 二、包版本与哈希

```text
包：baostock==0.9.3（PyPI）
文件：baostock-0.9.3-py3-none-any.whl（51125 字节）
SHA256：ACBD19403285BC4E254CEE8297CF0E2646AE2276E5AF7E549DEED3988AB02293
许可证：PyPI METADATA 声明 License: BSD License，classifier 为
  OSI Approved :: BSD License；wheel 内未附带许可证正文文件
  （dist-info 无 LICENSE）。本文件不作出版权/再分发法律结论。
版本一致性：PyPI 版本号 0.9.3；包内 BAOSTOCK_CLIENT_VERSION="00.9.30"
  （内部版本常量，与 PyPI 版本字符串不一致，属包自身命名差异）。
```

## 三、BaoStock 静态合同审计（依据安装包源码）

### login / logout

```text
login(user_id='anonymous', password='123456')
  - 默认匿名凭据，无需注册、账号、Token、Cookie、手机号；
  - 登录消息体包含 user_id/password，默认值即为 anonymous/123456；
  - error_code='0' 成功；10001005 登录数上限；10001006 权限不足。
logout(user_id='anonymous')：正常调用并关闭 socket。
```

### query_all_stock

```text
真实函数签名：query_all_stock(day=None)，day 缺省为本地当前日期；
返回 ResultData：error_code/error_msg；data.day 为服务器回显请求日；
fields 由服务器返回（实测 ['code','tradeStatus','code_name']）；
每页 2000 条（BAOSTOCK_PER_PAGE_COUNT），超过需翻页（next()）。
实测 2026-08-05：7329 行，含指数（sh.000xxx、sz.399xxx）、ETF、
基金、债券、B 股、北交所等非目标证券，必须按“交易所前缀+代码段”过滤。
SDK 内部分页由 BaoStock ResultData/next() 驱动，harness 无法逐页实施精确硬
上限；`universe_request_count` 因此仅作为观测/核算值，不属于
`--max-requests` hard cap。
```

### query_history_k_data_plus

```text
真实函数签名：
  query_history_k_data_plus(code, fields, start_date=None, end_date=None,
    frequency='d', adjustflag='3')
  - code 必须 8 字符（sh.600000 / sz.000001）；
  - start_date=end_date=T 支持精确单日；
  - adjustflag='3' 默认不复权；
  - 响应回显 start_date/end_date（服务器实际服务区间），可用于日期绑定验证；
  - fields 实测支持：date,code,open,high,low,close,preclose,tradestatus,
    pctChg,isST；
  - 停牌股返回当日单行：tradestatus='0'、OHLC/preclose 为同一价格、
    pctChg 为空（非缺失字段、非错误码）；
  - 指数/ETF 等同样返回单日行（依赖股票池过滤排除）。
```

### 传输与运行特征

```text
协议：自定义 TCP（public-api.baostock.com:10030），非 HTTP/HTTPS；
  CRC32 + 可选 zlib 压缩；库内无超时（recv 阻塞）——探测 harness 在
  login 后对 socket 设置 30 秒超时作为防护；
库内无重试、无限流、无本地缓存、无隐式数据持久化（仅内存 socket 状态）；
包内公开额外批量接口 query_daily_history_k_AStock(date)（单请求全市场
  日 K，分页上限 20000）——本轮未作为主路径，仅记录于候选矩阵。
```

### 未确认项（UNKNOWN）

```text
- 服务器端频率限制阈值：源码无客户端限流，服务端策略未公开；
- 数据最终性标记：无显式 is_final 字段（T+1 语义由请求日+回显推断）；
- 上游原始来源与许可细节：BaoStock 自建服务器，未公开上游链路。
```

## 四、交易日选择

```text
使用仓库离线交易日历（backend/data/cn_a_share_trade_calendar_v01.json，
SSE/SZSE 官方共识，2024-2026）：
T1 = 2026-08-05（最近已完成交易日，严格早于 2026-08-06 Asia/Shanghai）
T2 = 2026-08-04（T1 前一普通交易日）
T3 = 2026-08-05（最近 60 个交易日内，东财停复牌接口返回至少一只
  目标股票停牌事件的交易日；首个搜索日即满足）
无未来日期、无当日未结束数据、无“最近非空行情”回退。
```

## 五、股票池口径

```text
沿用现有 BK-11 合同（BK11_SHORT_TERM_FACTS_FEASIBILITY_V01.md §7）：
纳入：沪市主板（sh.60xxxx）、深市主板（sz.00xxxx）、创业板（sz.30xxxx）、
  科创板（sh.68xxxx）；ST/*ST 纳入；
排除：指数、ETF、LOF、基金、债券、可转债、B 股、港股、美股、期货、
  北交所（bj.8xxxxx/4xxxxx/920xxx）、退市整理期等。
过滤必须保留交易所前缀：sh.000001（上证指数）与 sz.000001（平安银行）
  数字相同，仅靠六位数字无法区分；过滤依据为代码+交易所字段，不按名称。
实际进入 sample/full/cross 的目标 universe 还必须满足：tradeStatus 只允许
字符串 '0' 或 '1'；出现未知/缺失/其他值时失败关闭，不进入 K 线探测。
```

## 六、探测结果

### 6.1 小样本（T1，120 只分层样本）

```text
样本策略：query_all_stock(T1) 过滤后按 板块前缀/停牌状态 分层、
  代码升序确定性轮转抽取 120 只（seed=0 仅决定轮转起点）；
结果：120/120 成功；失败 0、重试 0、空响应 0、日期不匹配 0、
  代码不匹配 0、重复 0、非法 pctChg 0、非法 OHLC 0、非法 tradeStatus 0、
  trade_status_mismatch 0；
确定性：前 5 只复用主探测结果、各追加 1 次复查，5/5 一致（共 5 次复查）；
请求观测：primary 120、retry 0、determinism 5、universe 4、session 2；
  controlled_probe=125（受 --max-requests 控制），uncontrolled_source=6，
  total_source=131；
延迟（含 determinism）：p50=32ms、p95=328ms、max=734ms；
总耗时 11.31s（11.05 controlled probe req/s）。
```

### 6.2 日期变化（T2，30 只样本）

```text
结果：30/30 成功；全部违规计数为 0（含 trade_status_mismatch 0）；
确定性 5/5（复用主结果+1 次复查）；
请求观测：primary 30、retry 0、determinism 5、universe 4、session 2；
  controlled_probe=35，uncontrolled_source=6，total_source=41；
总耗时 4.67s；
股票池随日期变化：T2 目标股票 5204 只、停牌 7 只（T1 为 5 只），
  证明 query_all_stock(day) 的 day 参数真实影响历史股票池。
```

### 6.3 全市场单日（T1，5204 只；成功运行）

```text
总目标：5204（query_all_stock 7329 行过滤 2125 行后）
请求观测：primary 5204、retry 0、determinism 5（复用主结果+1 次复查）、
  universe 4、session 2；controlled_probe=5209，uncontrolled_source=6，
  total_source=5215
成功：5204；失败 0；重试 0；空响应 0；日期不匹配 0；
  重复 0；非法 pctChg 0；非法 OHLC 0；非法 tradeStatus 0；
  trade_status_mismatch 0
确定性：5/5，一致性作为 breadth identity 必要条件
延迟（含 determinism）：p50=32ms、p95=485ms、max=5.81s、mean=111ms
总耗时：577.66s（约 9.6 分钟）；9.0 controlled probe req/s
预计每日生产耗时（单日全市场，含 5 次确定性复查）：约 9–10 分钟
```

### 6.3a 失败关闭证据（瞬时故障运行）

```text
复测期间一次运行在 495 次可控 K 线请求时触发 failure_rate 熔断：
  3 只股票传输失败（各重试 1 次后仍失败，6/495 ≈ 1.21% > 1%）；
  电路立即停止（processed=492、circuit_open=failure_rate、
  breadth_identity=false），未继续无意义请求；
随后一次运行 5204/5204 成功（见 6.3）。该现象证明失败率熔断与
  identity 失败关闭在真实环境下按设计生效，也记录 BaoStock 存在
  低频瞬时传输错误（可重试后恢复）。
```

### 6.4 市场宽度（T1）

```text
advance_count = 3427（pctChg > 0）
decline_count = 1599（pctChg < 0）
flat_count    = 173（pctChg == 0）
suspended_count = 5（query_all_stock tradeStatus='0'，与 K 线
  tradestatus='0' 一致）
eligible_count = 5204（目标股票池）
valid_count    = 5199 = 3427 + 1599 + 173
恒等式：eligible == valid + suspended（5204 == 5199 + 5）成立
缺失 pctChg：0（停牌股空 pctChg 为预期语义，不计缺失）
状态一致性：universe 与 K 线 tradeStatus 均严格为 0/1；
  trade_status_mismatch=0、invalid_tradestatus=0；请求失败 0、空响应 0、
  日期/代码/重复/非法计数 0；股票池重复 0、状态冲突 0；
  processed == target_count；circuit 空；controlled probe budget 未耗尽；
  determinism 5/5 且 complete → breadth_identity=true
```

### 6.4a 股票池失败关闭

```text
query_all_stock 重复目标代码不再静默保留首次值：
- duplicate_code_count：同状态重复行计数（本次 0）；
- conflicting_status_count：同代码不同状态计数（本次 0）；
  任一冲突 > 0 → 来源合同失败，sample/full/cross 全部停止探测；
- 目标 universe 任一 tradeStatus 非 '0'/'1' → invalid universe trade status，
  在任何 K 线探测前失败关闭；
- 重复 > 0 且无冲突 → 至少 contract_warning，不得生成 FULL 结论；
- 目标数量 > FULL_MAX_TARGETS（6500）→ universe_too_large，失败关闭，
  不得静默截断（本次 5204 ≤ 6500 不触发）。
```

### 6.5 停牌语义

```text
停牌股（query_all_stock tradeStatus='0'）在单日 K 线中返回：
  tradestatus='0'、OHLC/preclose=同一价格（通常为前收）、pctChg=''；
活跃股返回 tradestatus='1' 与有限 pctChg；
未观察到“停牌返回空响应”的行为（5204 只中空响应 0）；
缺失 pctChg 不被归入停牌（停牌由 tradeStatus 字段决定，不反推）。
K 线 tradestatus 缺失、空串、'-'、数字型或其他值均属于
invalid_tradestatus，不接受宽松解释。
```

### 6.6 东财指定日期停复牌交叉验证（T3=2026-08-05）

```text
接口：datacenter-web /api/data/v1/get
  reportName=RPT_CUSTOM_SUSPEND_DATA_INTERFACE
  filter=(MARKET="全部")(DATETIME='YYYY-MM-DD')，pageSize=500 有界分页；
  （filter 必须包含 MARKET="全部"，参考 AKShare 公开实现 stock_tfp_em）
东财记录语义：该接口返回“停复牌事件记录”，SUSPEND_START_DATE 可跨多个
  日期（实测 DATETIME='2026-08-05' 的记录起始日为 07-27 至 08-06）；
  不是“当日停牌集合”。按“T 日处于停牌”（SUSPEND_START_DATE <= T 且
  截止时间空或 > T）过滤后：

  BaoStock 停牌（目标池）    = 5
  东财 T 日停牌（目标池）     = 5
  交集                        = 5
  仅 BaoStock                 = 0
  仅东财（目标池）            = 0
  Jaccard（目标池）           = 1.0

全口径（含 B 股 200706 瓦轴B）：东财 6、交集 5、Jaccard=0.8333，
  唯一差异为 B 股（非目标证券，BaoStock 侧按口径排除）。
差异原因可解释：事件日期语义 + 证券范围（B 股）+ 日内停复牌
  （如 603221 停至 08-05 15:00，08-05 当日仍计停牌）。
```

### 6.7 东财涨停/跌停/炸板池验证（T1，正数事件日）

```text
原始接口（astock.em_zt_topic_pool，HTTPS）：
  getTopicZTPool(20260805)：103 行，目标池 102；
  getTopicZBPool(20260805)：43 行，目标池 42；
  getTopicDTPool(20260805)：0 行（空池，来源可用，但不得视为合法 0）；
  三个日期的池内容不同（08-03: 75、08-04: 138、08-05: 103），
  证明 date 参数影响返回内容。

日期绑定关键发现：
  响应内唯一日期字段 data.qdate 恒等于“服务器查询日”
  （2026-08-06 请求 08-03/08-04/08-05 三个日期，qdate 均为 20260806）；
  已批准适配器（short_term_limit_up_pool_adapter）将 data.qdate 作为
  交易日期候选，对历史日期请求返回 TRADE_DATE_MISMATCH / unavailable；
  final producer（三次观测）在首个观测即失败关闭（SOURCE_UNAVAILABLE，
  completed_observations=1）。

结论：池数据可达且随日期变化，但“池所属交易日”无法从响应载荷证明；
  已批准适配器/生产者的日期绑定合同与真实载荷语义冲突（Blocker 3 保持
  OPEN）。本阶段禁止实现涨跌停价规则，不修改适配器。
```

## 六A、此前修复记录（2026-08-06）

```text
- determinism 复用主探测结果，每只只追加 1 次复查请求；
- request_count 明确为 primary+retry+determinism 的 K 线调用计数；
- duplicate_code_count / conflicting_status_count 与状态匹配检查已加入；
- FULL_MAX_TARGETS=6500，超过失败关闭；
- 输出继续保留 session/universe/primary/retry/determinism 分列核算。
```

## 六B、Issue #48 最新审查关闭口径（2026-08-07）

```text
P1-1 请求预算重新定义：
  - --max-requests 只控制 query_history_k_data_plus 的
    primary/retry/determinism；
  - login/logout 与 query_all_stock SDK 内部分页不属于该 hard cap；
  - request_accounting 明确输出 budget_scope、controlled_probe_request_count、
    uncontrolled_source_request_count 与 total_source_request_count；
  - universe_request_count 是分页观测/核算值，不声称可逐页精确阻断。

P1-2 非正预算：
  - CLI 默认值改为 None（“省略参数”与“显式 0”不再混为一谈）；
  - sample/full 显式 0 或负数必须在 client.login() 前抛错/返回 rc=2；
  - sample 上限 150，full 上限 6600 保持。

P1-3 tradeStatus + determinism：
  - 进入任何 sample/full/cross K 线工作前，目标 universe tradeStatus
    必须严格为字符串 '0'/'1'；
  - K 线 tradestatus 同样严格为字符串 '0'/'1'，缺失/空/'-'/其他类型
    均计 invalid_tradestatus；
  - breadth_identity 同时要求 invalid_tradestatus=0、trade_status_mismatch=0
    以及 determinism_consistent=true；
  - determinism requested 时 incomplete 或任一复查不一致均使 identity=false。

P2-1 文档性能口径：
  - 全市场成功实测统一为 577.66s / 约9.6分钟 / 9.0 req/s；
  - 删除此前所有冲突性能口径。
```

## 七、legal-zero 结论

```text
legal-zero = NOT_PROVEN
依据：跌停池 08-05 为空（0 行）但无任何来源证明“当日全市场确实无跌停”；
  已批准适配器 legal_zero 恒 False；本阶段不实现涨跌停价规则，
  不根据 BaoStock preclose 重建价格限制规则。
零事件日不生产或只能 partial/unavailable。
```

## 八、数据许可与稳定性风险

```text
- BaoStock：免费匿名；BSD（PyPI 元数据）；自建服务器，非交易所直发；
  服务条款与上游链路未公开；最终成功全市场探测约 9.0 req/s，5204/5204；
- 东财：Tier B 商业源，无公开 API 文档，许可 unclear；存在限流/空响应/
  访问控制风险（既有审计已记录）；qdate 语义冲突需适配器合同修正；
- 数据保留边界：本仓库只提交聚合统计与脱敏摘要；不提交完整股票列表、
  完整行情行、原始响应、请求 URL 或异常原文。
```

## 九、免费来源候选矩阵

| 候选 | 免费 | 注册 | Token | 历史指定日期 | 历史股票池 | 停牌状态 | 全市场截面 | 涨停/跌停/炸板 | 连板 | 日期绑定 | 请求规模 | 稳定性 | 许可证 | 适合字段 | 不能承担字段 | 进入下一阶段 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BaoStock | 是 | 否 | 否 | 是（单日 K，日期回显） | 是（query_all_stock(day)，tradeStatus） | 是（tradeStatus/tradestatus） | 是（逐股单日，全市场 ~5200 可控 K 线请求 ≈9.6 分钟） | 否（无涨跌停池） | 否 | 强（请求日回显+行内日期） | 中等（最终实测 9.0 req/s，5200/日） | 最终成功运行 5204/5204 | BSD（PyPI 元数据） | breadth、suspended/eligible、pctChg 分布 | 涨跌停/炸板/连板 | 是（breadth/停牌主源） |
| 东财现有接口（push2ex 三池） | 是 | 否 | 否 | 是（date 参数影响内容） | 否 | 否 | 否（仅池） | 是（ZT/ZB/DT 池） | 是（lbc） | 未证明（qdate=查询日，载荷无池日期） | 单日 3–4 请求 | 间歇风控风险 | unclear | 涨跌停/炸板/连板池 | 日期绑定证明、legal-zero | 有条件（需适配器合同修正） |
| 东财指定日期停复牌接口 | 是 | 否 | 否 | 是（DATETIME） | 否 | 是（事件记录，需过滤“T 日处于停牌”） | 否 | 否 | 否 | 中（事件日期语义需解释） | 单日 1–2 请求 | 本日稳定 | unclear | 停牌交叉验证 | 全市场截面、breadth | 是（交叉验证源） |
| AKShare | 是（开源库） | 否 | 否 | 是（封装上游） | 是 | 是 | 是 | 是 | 是 | 依赖其上游封装 | — | 依赖上游 | MIT（库本身） | 仅作接口实现参考 | 不作为直接依赖（本任务未安装） | 否（参考） |
| Ashare | 免费（社区库） | 否 | 否 | 依赖上游 | 依赖上游 | 依赖上游 | 是 | 部分 | 否 | 依赖上游 | 依赖上游 | 依赖上游 | unclear | 未探测 | 未探测 | 否（未实测） |
| easy-tdx / pytdx / mootdx | 免费（社区协议） | 否 | 否 | 是（K 线历史） | 否 | 部分（价格缺失推断） | 是（K 线逐股） | 否 | 否 | 中（无池） | 大（逐股） | 服务器 IP 老化、海外不可达 | unclear | K 线 | 涨跌停池/停牌状态证明 | 否（既有审计记录不可靠） |
| Tushare | 否（积分/付费基线） | 是 | 是 | 是 | 是 | 是 | 是 | 部分 | 是 | 强 | 受积分限制 | 商业稳定 | unclear | — | — | 否（付费基线，本轮未请求） |

## 十、结果分类

```text
结果：FEASIBLE_ZERO_COST_PARTIAL

成立面：
- advance/decline/flat/suspended/eligible 可可靠生成（BaoStock，
  全市场验证，恒等式成立，停牌交叉验证一致）；
- 全部数据成本为 0（无付费 API、无 Token、无 Cookie、无账号）；
- 最终成功实测为 577.66s / 约9.6分钟 / 9.0 req/s，预计每日约9–10分钟。

不足面（数据只能进入 partial，不允许标记 normal）：
- 涨跌停活动日期绑定未证明（qdate=查询日，已批准适配器失败关闭）；
- legal-zero NOT_PROVEN（0 值日不可生产）；
- 连板/ladder 依赖的 final producer 在历史日期当前不可用。
```

## 十一、下一阶段建议（不自动实施）

```text
1. 先完成本研究分支最新审查项的离线验证与独立复审；
2. 只有 P0=P1=P2=0 后创建 Draft PR；
3. 后续若接受“零事件日 unavailable/partial、正数日仅 partial”口径，
   再单独评估东财池适配器日期绑定合同与 Blocker 3；
4. 可评估从 PR #47 抽取 v0.2 composer/store 设计并改接 BaoStock breadth；
5. 不自动开始生产实现、调度、历史回填、Slice 4 或
   layered_promotion_rates。
```

## 十二、本轮未触碰

```text
- 未修改 backend 生产模块、frontend、requirements、package lock、
  GitHub workflow、fact store、history API、Data Health、Daily Review；
- 未写 short_term_facts.sqlite3 或任何用户正式数据库；
- 未触碰 PR #47（Head/描述/分支均未动）；未触碰 PR #43；
- 未安装 AKShare / easy-tdx / Tushare；未新增生产依赖；
- 未实现调度、回填、Slice 4、layered_promotion_rates；
- Blocker 2 OPEN；Blocker 3 OPEN；Blocker 6 PARTIALLY CLOSED。
```

## 十三、测试与验证

```text
研究代码：tools/research/bk11_baostock_probe.py
原有测试：backend/tests/test_bk11_baostock_probe.py（62 项离线测试）
关闭测试：backend/tests/test_bk11_baostock_probe_contract_closure.py
文档：docs/research/BK11_FREE_SOURCE_FEASIBILITY_V01.md（本文件）
状态：docs/research/EXECUTION_STATE.md

2026-08-06 历史基线：3443 passed（基线3381 + 62）、11 deselected、
  1既有warning、failed=0；前端291 passed；npm run build通过。
2026-08-07 最新审查关闭后的测试结果以本分支新 Head 的 CI/独立复审为准，
  在完成前不得把本阶段标记为 Ready/生产接入。
live 探测：不因本次合同修复重跑全市场；仅允许后续小样本 smoke，
  不把 live 探测加入 GitHub CI。
```
