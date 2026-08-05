# BK-11 external-source holiday probe v0.1（修正版）

> 证据工件：`docs/research/BK11_EXTERNAL_SOURCE_HOLIDAY_PROBE_V01.json`
> 本文件为修正版（correction revision 1），修正授权合规、指标语义、
> 证据可复算性与 Blocker 决策。上一版（`1cbb11e`）中的 Blocker 2
> "candidate CLOSED" 声明已正式撤回。

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO FOR FURTHER SOURCE DESIGN ONLY |
| Slice 2I task acceptance | CHANGES REQUIRED / authorization non-compliant evidence retained |
| Blocker 2 | OPEN（原 candidate CLOSED 已撤回） |
| Blocker 3 | OPEN |
| Blocker 6 | PARTIALLY CLOSED（未探测 legal zero） |
| alternative source date semantics | VERIFIED_BY_PAYLOAD_DATA_DATE |
| consecutive lbc semantics | NOT_VERIFIED |
| pagination completeness | NOT_VERIFIED |
| 替代来源建议 | ADOPT_FOR_FURTHER_DESIGN |
| implementation_allowed | false |
| production adoption authorized | false |

`ADOPT_FOR_FURTHER_DESIGN` 仅表示来源值得进入后续来源设计与字段语义
研究；不代表已接入生产、不代表已批准替换东财、不代表已允许
`layered_promotion_rates`、不代表 Blocker 2 已满足。

本轮实际发出 26 次数据请求，超过授权上限 20 次（超支 6 次）。如实披露
不构成授权豁免；历史请求不可撤销；本工件只能作为非权威研究参考，
不能作为 Slice 2I 合规验收或 Blocker 2 关闭证据。

## 2. Scope and Non-goals

### Scope

- research-only：只读外部公开数据探测 + 标准化 + 机械计算
- 为 Blocker 2 补充节假日边界（Pair C）跨日 stock_code / 计数证据
- 评估一个替代公开来源的历史日期绑定、稳定性、字段完整性
- 与既有东财 Slice 2D 工件（Pair A / Pair B）交叉核验
- 输出 adopt / reject / insufficient-evidence 建议

### Non-goals

- 不实现 layered_promotion_rates
- 不修改生产代码 / adapter / producer / validator / gate
- 不接入新数据源、不新增运行时依赖
- 不创建 API / 前端 / 数据库 / 调度任务
- 不修改 Blocker 6 的 legal-zero 合同
- 不创建 PR、不 merge、不自行启动后续子阶段
- 不探测或推断 legal zero

## 3. Existing Evidence Baseline

以下为既有已批准证据（本轮不重复声称首次获得）：

```text
Pair A: 2026-07-30 -> 2026-07-31, ordinary_consecutive
Pair B: 2026-07-24 -> 2026-07-27, cross_weekend
Pair C: 2026-06-18 -> 2026-06-22, post_holiday
```

既有结论（Slice 2D / Slice 2F / Slice 2H）：

```text
Pair A: 东财非空、两轮稳定、可机械复算
Pair B: 东财非空、两轮稳定、可机械复算
Pair C: 东财两日均 EMPTY_UNEXPLAINED
Blocker 2: OPEN（Pair C 空数据导致未闭合）
Blocker 3: OPEN（东财 payload 无可独立验证的 trade_date 字段）
```

东财 Pair A/B 标准化工件来自
`docs/research/BK11_LAYERED_PROMOTION_PROBE_V01.json`（已批准）。

## 4. Source Candidate Matrix

评估了三个候选，均按最低条件筛选（无需登录 / API key / Cookie /
Token / 付费账户 / 验证码绕过 / 伪造凭据；允许按历史交易日查询；
具有明确日期语义；能直接提供或机械推导 stock_code + 计数）：

| 候选 | domain | 凭证 | 历史日期 | payload 日期字段 | 选择 |
|------|--------|------|----------|------------------|------|
| 同花顺涨停池 dataapi | data.10jqka.com.cn | 无 | 支持 date=YYYYMMDD | data.date（实测存在） | 选中 |
| Tushare 涨停列表 | api.tushare.pro | 需 token | 支持 trade_date | trade_date | 拒绝：凭证条件不满足 |
| 东财 getTopicZTPool 历史 | push2ex.eastmoney.com | 无 | 支持 date 参数 | 无（既有 Blocker 3 缺口） | 拒绝：与既有源同源且无 payload 日期 |

完整矩阵（access_method / response_format / rate_limit /
retention / terms 观察）见 JSON `source_candidate_matrix`。

来源文档依据：

- 同花顺涨停池端点用法来自本机已安装的公开数据技能记录
  （a-stock-data，2026-07 实测记录），本轮以实际请求验证
  （observed fact）。
- Tushare 需 token 为公开 API 文档说明（source documentation）。
- 东财 payload 无日期字段为既有 Slice 2D 已验证结论（observed fact）。

## 5. Selected Source

```text
source_name: 同花顺涨停池 dataapi (limit_up_pool)
domain: data.10jqka.com.cn
endpoint: /dataapi/limit_up/limit_up_pool
access: HTTP GET, User-Agent + Referer only（实测 200，零鉴权）
request params:
  page=1 limit=200
  field=199112,10,9001,330323,330324,330325,330326,9002,330329,
         133971,133970,1968584,3475914,9003,9004
  filter=HS,GEM2STAR   （沪深主板+创业板+科创板）
  order_field=330324 order_type=0
  date=YYYYMMDD
payload date field: data.date（实测值 = 请求日期 YYYYMMDD）
stock code field: info[].code（六位数字字符串）
count field: info[].high_days
  "首板" -> window_limit_up_count = 1
  "N天M板" -> window_limit_up_count = M
response format: JSON
```

选择理由（observed fact + mechanical derivation）：

```text
1. 唯一同时满足全部最低条件的候选
2. payload 自带 data.date，可做响应内日期绑定
3. 每条记录自带 first_limit_up_time（unix 秒，探针期已核对）
4. 与东财不同域名、不同风控面，适合做独立交叉核验
```

## 6. Request Discipline

### 设计参数

```text
串行、无并发
相邻数据请求间隔 >= 2.2 秒（配置）
单请求 timeout <= 15 秒
每请求最多重试 1 次（实测重试 0 次）
无 Cookie / Token / 认证 Header / 设备指纹 / 代理池 / IP 轮换
无登录、无验证码绕过
```

### 请求清单与授权合规

```text
授权上限: 20
实际合计: 26
超出: 6
authorization_compliance: false
evidence_authority: non_authoritative_research_reference
task_acceptance: failed_due_to_request_budget_exceeded
```

构成：

```text
12 条正式主请求 ledger（最终轮）
12 条 superseded ledger（第一轮主请求，因解析/持久化缺陷被取代）
2 次 unledgered 请求（结构预检 x1 + 字段语义确认 x1）
```

第一次主探针脚本存在解析缺陷（high_days="首板" 未处理）与持久化缺陷
（normalized rows 未落盘），证据不可用，必须重跑 12 次主请求。
所有请求仍遵守串行 / >=2.2s / <=15s / 无凭据纪律，但 20 次授权上限
被超出 6 次；如实披露不构成授权豁免，历史请求不可撤销。

### 间隔定义（修正）

```text
interval_definition:
  previous request finished_at_utc -> current request started_at_utc

minimum_ledger_interval_seconds（24 条 ledger 按时间戳复算）: 2.200
ledger_interval_compliance_at_recorded_precision: true
global_interval_compliance: NOT_VERIFIED
```

`global_interval_compliance = NOT_VERIFIED` 的原因：两次 unledgered
请求没有完整 started_at / finished_at 记录，无法纳入全部 26 次请求的
全局相邻间隔复算。不得声称全部 26 次请求的最小实测间隔已验证。

## 7. Data-retention Boundary

JSON 工件只保留：

```text
source metadata / request ledger / requested date
payload date evidence / stock_code / window_limit_up_count
标准化计数 / SHA256 / 跨日计算结果 / 异常分类
```

未保留、未提交：

```text
股票名称 / 价格 / 成交额 / 行业 / 封单数据 / 完整原始响应
逐记录 first_limit_up_time / 逐记录原始 high_days（N/M）
Cookie / Token / 认证 Header / 设备指纹 / 访问控制页面
异常堆栈中的敏感 URL 参数
```

一次性脚本与缓存未提交（任务结束前已删除）。

## 8. Date-binding Evidence

### 可复算证据：data.date（observed fact，已提交）

12 次正式主请求全部返回 `data.date`，解析后与请求日期一致：

```text
2026-06-18 -> data.date=20260618, match=true
2026-06-22 -> data.date=20260622, match=true
2026-07-24 -> data.date=20260724, match=true
2026-07-27 -> data.date=20260727, match=true
2026-07-30 -> data.date=20260730, match=true
2026-07-31 -> data.date=20260731, match=true
```

```text
alternative source date semantics: VERIFIED_BY_PAYLOAD_DATA_DATE
依据: 12/12 正式主请求的 data.date 与 requested date 匹配
```

### 不可复算证据：逐记录时间戳（REPORTED_NOT_REPRODUCIBLE）

```text
reported record date matches: 1046 / 1046
status: REPORTED_NOT_REPRODUCIBLE
```

探针执行期曾用 `info[].first_limit_up_time`（unix 秒，Asia/Shanghai）
核对逐记录交易日期，报告为 1046/1046 匹配；但逐记录时间戳未保留在
工件中，C 无法离线复算，不得作为独立机械证据。

仅 URL 参数含日期不作为证据；本来源的日期绑定以响应内 `data.date`
为准。

## 9. Two-round Stability

每个日期两轮独立读取，逐项比较：

```text
canonical normalized rows: 完全相等（6/6 日期）
normalized_rows_sha256:    完全相等（6/6 日期）
payload date:              完全一致（6/6 日期）
invalid / duplicate / excluded counts: 全部 0
```

SHA256 序列化合同（本工件全部 hash 均按此离线复算）：

```python
json.dumps(
    rows,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

要求：rows 按 stock_code 升序；每行字段集合固定；列表顺序参与 hash。

```text
2026-06-18: 91 行, sha 3e64dd92ef89...
2026-06-22: 132 行, sha b82c8ee76ddc...
2026-07-24: 40 行,  sha 467550a08e59...
2026-07-27: 111 行, sha 532f4fa13dad...
2026-07-30: 51 行,  sha c869a7c2d23d...
2026-07-31: 98 行,  sha c763b960e78f...
```

> 注意：因字段由 `lbc` 重命名为 `window_limit_up_count`，全部 SHA256
> 已重新计算，JSON `date_results` 与 `request_ledger` 中为唯一权威值；
> 本文只维护前缀，完整 hash 以 JSON 为准（DRY）。

## 10. Pair A Results（ordinary_consecutive）

```text
previous: 2026-07-30, 51 行（page-1）, 两轮稳定, 日期绑定 true
current:  2026-07-31, 98 行（page-1）, 两轮稳定, 日期绑定 true
```

跨日（提交的窗口计数值）：

```text
shared_identity: 10
previous_only: 41
current_only: 88
window_count_increment_count: 10 / 10（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

机械比率（denominator > 0 层）：

```text
N=1: 38 -> 6, rate=0.1579
N=2: 8  -> 1, rate=0.1250
N=3: 1  -> 1, rate=1.0000
N=4: 3  -> 1, rate=0.3333
N=8: 1  -> 1, rate=1.0000
```

语义限定：

```text
metric: window_limit_up_count（high_days M），非连续板数
scope: page-1 observed dataset，未证明来源完整
mechanical scope: 对已提交 page-1 窗口计数数据集可机械复算
不得称为: 连续板晋级率 / Blocker 2 closure evidence / 完整来源分母
```

## 11. Pair B Results（cross_weekend）

```text
previous: 2026-07-24, 40 行（page-1）, 两轮稳定, 日期绑定 true
current:  2026-07-27, 111 行（page-1）, 两轮稳定, 日期绑定 true
```

跨日（提交的窗口计数值）：

```text
shared_identity: 8
previous_only: 32
current_only: 103
window_count_increment_count: 8 / 8（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

机械比率：

```text
N=1: 21 -> 3, rate=0.1429
N=2: 13 -> 2, rate=0.1538
N=3: 3  -> 1, rate=0.3333
N=4: 2  -> 2, rate=1.0000
N=9: 1  -> 0, rate=0.0000
```

语义限定：同 §10（window-count / page-1，非连续板晋级）。

## 12. Pair C Holiday Results（post_holiday）

```text
previous: 2026-06-18, 91 行（page-1）, 两轮稳定, 日期绑定 true
current:  2026-06-22, 132 行（page-1）, 两轮稳定, 日期绑定 true
```

跨日（提交的窗口计数值，跨端午假期 2026-06-19 非交易日）：

```text
shared_identity: 23
previous_only: 68
current_only: 109
window_count_increment_count: 23 / 23（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

机械比率：

```text
N=1: 64 -> 14, rate=0.2188
N=2: 17 -> 4,  rate=0.2353
N=3: 9  -> 4,  rate=0.4444
N=5: 1  -> 1,  rate=1.0000
```

Pair C 状态：

```text
single-source holiday observation（东财两日 EMPTY_UNEXPLAINED）
eastmoney comparison: unavailable
not sufficient to verify consecutive lbc
not sufficient to close Blocker 2
```

## 13. Eastmoney Cross-source Comparison

与已批准东财 Slice 2D 工件交叉核验（Pair A / B 四日期；
eastmoney 行先按 universe 规则过滤 4/8/92/9 前缀）：

```text
2026-07-30: em=51, ths=51, shared=51, em_only=0, ths_only=0,
            same count=48, different=3, jaccard=1.0000
2026-07-31: em=98, ths=98, shared=98, em_only=0, ths_only=0,
            same count=94, different=4, jaccard=1.0000
2026-07-24: em=40, ths=40, shared=40, em_only=0, ths_only=0,
            same count=38, different=2, jaccard=1.0000
2026-07-27: em=111, ths=111, shared=111, em_only=0, ths_only=0,
            same count=98, different=13, jaccard=1.0000
```

identity 结论（observed fact）：四日期提交的 page-1 股票集合与东财
完全一致（jaccard 1.0，0 个 only 代码）。

计数差异（observed fact + inference，已逐项枚举）：

```text
300 个共享代码比较中 278 个一致（92.7%），22 个不一致
全部为同一模式：提交的窗口计数值 M >= 2，而东财 consecutive lbc = 1
（即同花顺 "N天M板" 中 N > M 的行）
```

22 项差异的正式名称：

```text
observed discrepancy between submitted window-count value
and Eastmoney consecutive lbc
```

不得称其为"已完全解释的系统性冲突"，也不得作为 Blocker 关闭证据。
规则 B（N>M 样本中东财连板均为 1）仅为 sample inference，未用于提交
计算、未证明普遍性、不可由提交的原始字段复算。

```text
Pair A 分类: PARTIALLY_CONSISTENT（page-1 身份一致；计数差异 7/149）
Pair B 分类: PARTIALLY_CONSISTENT（page-1 身份一致；计数差异 15/151）
Pair C 分类: NOT_COMPARABLE（东财两日为空）
```

交叉验证不等于证明东财 payload 日期字段；东财 Blocker 3 维持 OPEN。

## 14. Cross-day Count Verification

对 A / B / C 三组，previous 层 N 的机械比率：

```text
denominator_N = previous 中 window_limit_up_count == N 的唯一股票数
numerator_N   = 上述股票中 current 存在且 count == N+1 的唯一股票数
rate_N        = round(numerator_N / denominator_N, 4)
```

结果（mechanical calculation；完整 normalized rows 已提交，可离线
独立复算）：

```text
Pair A: N=1..4,8 层全部给出 denominator/numerator/rate
Pair B: N=1..4,9 层全部给出
Pair C: N=1..3,5 层全部给出
```

共享股票（两日均在池内）的提交计数值全部精确 +1：

```text
41/41 submitted window-count values increased by exactly 1
```

必须明确（inference / 否定表述）：

```text
该机械现象不证明连续板数 N -> N+1。
```

所有 denominator / numerator / rates 均标记：

```text
derived from submitted page-1 normalized rows
not proven complete for the source
```

## 15. Blocker 2 Decision

```text
Blocker 2: OPEN
（上一版 "candidate CLOSED pending independent review" 已正式撤回）
```

```text
candidate_closed: false
closure_authorized: false
```

criteria 真实状态：

```text
three_date_pairs_present:           true
payload_date_binding_verified:      true（data.date 12/12）
two_round_stability_observed:       true
identity_sets_reproducible:         true（提交的 page-1 集合）
request_budget_compliant:           false（26 > 20）
consecutive_lbc_semantics_verified: false
raw_mapping_evidence_reproducible:  false（未保留逐记录 high_days）
pagination_completeness_verified:   false
holiday_pair_cross_source_verified: false（Pair C 单来源）
```

blocking reasons：

```text
REQUEST_BUDGET_EXCEEDED
CONSECUTIVE_LBC_SEMANTICS_UNVERIFIED
RAW_HIGH_DAYS_MAPPING_NOT_RETAINED
PAGINATION_COMPLETENESS_UNVERIFIED
HOLIDAY_PAIR_SINGLE_SOURCE_ONLY
```

以上仅为研究工件字段，不构成正式 reason-code 合同。

## 16. Blocker 3 Decision

```text
Blocker 3: OPEN（整体）
```

区分两个问题：

```text
A. 替代来源自身历史日期语义: VERIFIED_BY_PAYLOAD_DATA_DATE
   - response.data.date == 请求日期（12/12 正式主请求）
   - 逐记录时间戳 1046/1046 为 REPORTED_NOT_REPRODUCIBLE，
     不作为独立机械证据

B. 东财 getTopicZTPool 日期语义: 仍按既有证据（payload 无日期字段，
   本轮未取得直接针对东财 payload 日期绑定的新证据）
```

```text
replacement_or_crosscheck_path: candidate available pending
                                source adoption decision
```

不得仅因替代来源可靠就宣称东财 Blocker 3 已关闭。

## 17. Blocker 6 Boundary

```text
Blocker 6: PARTIALLY CLOSED（不变）
```

本轮未探测 legal zero。以下均不作为 legal-zero 证据：

```text
单次空数组 / 两次相同空数组 / HTTP 200 + 空数组
替代来源也为空 / 无涨停新闻 / 页面显示 0
```

## 18. Source Recommendation

```text
recommendation: ADOPT_FOR_FURTHER_DESIGN
production adoption authorized: false
architecture decision required: true
```

permitted meaning（允许的含义）：

```text
替代来源具有可复核的 data.date；
身份集合在 Pair A/B 与东财高度一致；
可作为后续来源设计和字段语义研究候选。
```

prohibited meaning（禁止的含义）：

```text
已验证 consecutive lbc
已验证完整分页
已满足 Blocker 2
已批准生产采用
已证明节假日晋级率
```

优势（observed fact，收窄后）：

```text
零鉴权公开 JSON 端点（仅 UA + Referer，12/12 主请求 HTTP 200）
payload 自带 data.date，日期绑定在响应内部成立（12/12）
历史查询已验证六个固定日期（含节假日对，page-1 数据可用）
Pair A/B 提交的 page-1 身份集合与东财一致（jaccard 1.0）
两轮稳定性 6/6
41/41 submitted window-count values increased by exactly 1
  （机械现象，非连续板晋级证明）
```

缺陷（observed fact + inference）：

```text
high_days 为窗口涨停次数（N天M板），非连续板数；
  N>M 行与东财 consecutive lbc 存在 22/300 已枚举差异
逐记录原始 high_days / N / M 未保留，映射不可独立复核
分页完整性 NOT_VERIFIED（仅 page=1 limit=200）
非官方内部端点：无 SLA、无许可证声明、可能随时变更
```

未验证项：

```text
consecutive lbc semantics / pagination completeness / 节假日晋级率
```

历史覆盖 / 日期绑定 / 字段完整性 / 稳定性 / 与东财一致性 /
访问限制 / 数据保留边界 / 维护成本 / 依赖影响：完整条目见 JSON
`source_recommendation`。

```text
维护成本: 中高（非官方端点 schema 可能漂移，采用前必须重验证）
依赖影响: 探针零新增依赖；生产适配器需直连 HTTP + 串行限流
```

## 19. Risks and Limitations

```text
1. 授权不合规（证据缺陷）: 26 次 vs 20 次授权上限；
   authorization_compliance=false；
   task_acceptance=failed_due_to_request_budget_exceeded；
   披露不构成豁免；工件仅可作非权威研究参考
2. 指标语义: 提交值为窗口涨停次数（high_days M / 首板=1），
   不是连续涨停板数；consecutive_lbc_verified=false
3. 原始映射不可复核: 未保留逐记录 high_days / N / M
4. 分页完整性 NOT_VERIFIED: 仅 page=1 limit=200
5. 逐记录时间戳 REPORTED_NOT_REPRODUCIBLE: 1046/1046 为报告值，
   未保留原始时间戳，C 无法离线复算
6. 全局间隔 NOT_VERIFIED: 两次 unledgered 请求无完整时间戳 ledger
7. 规则 B 仅为样本推断: 未用于提交计算、未证明普遍性、
   非 Blocker 关闭规则
8. Pair C 单来源: 节假日证据仅替代来源，东财无法交叉
9. 非官方端点: 无 SLA / 无许可证声明
10. 历史覆盖: 仅验证六个固定日期
```

## 20. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO FOR FURTHER SOURCE DESIGN ONLY**

- 替代来源可行性（研究层面）：部分通过（data.date 可复核、
  两轮稳定、page-1 身份与东财一致）
- 节假日 page-1 观测：新增（Pair C 91 -> 132，23 个共享身份
  的提交计数值全部精确 +1；单来源、非连续板证明）
- Slice 2I task acceptance：CHANGES REQUIRED /
  authorization non-compliant evidence retained
- Blocker 2：OPEN（撤回候选关闭）
- Blocker 3：OPEN（整体）
- Blocker 6：PARTIALLY CLOSED（未变）
- implementation_allowed：false
- production adoption authorized：false

剩余阻断：

```text
- 授权预算超支（26 > 20），任务验收不通过
- consecutive lbc 语义未验证（需保留逐记录 high_days 或等价机制）
- 分页完整性未验证
- Pair C 节假日证据仅单来源
- 东财 Blocker 3 仍 OPEN（本轮只验证替代来源）
- 替代来源生产采用未授权（需架构 + 条款评估）
- layered_promotion_rates 生产实现仍不允许
```

完成并推送后停止；未通知 C；未启动下一子阶段。
