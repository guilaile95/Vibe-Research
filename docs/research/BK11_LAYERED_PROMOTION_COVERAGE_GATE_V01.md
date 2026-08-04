# BK-11 layered-promotion coverage eligibility gate v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 2 | OPEN |
| Blocker 3 | OPEN |
| Blocker 5 | CLOSED for T+1 completed-session snapshots（沿用 Slice 2F） |
| Blocker 6 | PARTIALLY CLOSED |
| Blocker 7 | CLOSED（沿用适配器 universe 合同） |
| Blocker 8 | candidate CLOSED pending independent review — partial/unavailable/invalid 强制 rates=null，正式关闭由独立复审确认 |
| Blocker 9 | CLOSED（沿用 Slice 2G） |
| implementation_allowed(layered_promotion_rates) | false |

`coverage_eligible != implementation_allowed`。Blocker 8 关闭不代表生产
晋级率已获准；Blocker 2 / 3 / 6 仍阻断生产实现。

## 2. Scope and Non-goals

### Scope

- 纯离线、纯确定性 coverage eligibility gate
- 消费 Slice 2F final-snapshot producer 的 previous/current 结果
- 严格验证 producer 顶层合同、nested adapter 完整覆盖与日期先后关系
- partial / unavailable / invalid / 不完整覆盖 → 机械强制
  `layered_promotion_rates = null`（`rates_policy = must_be_null`）
- complete 不计算 rates（不接收、不透传任何晋级率）

### Non-goals

- 不调用 final snapshot producer / pool adapter / astock
- 不计算 numerator / denominator / rate
- 不接收 proposed / candidate / computed rates
- 不注册到应用入口 / 调度器 / API / 生产决策链
- 不推进 Blocker 2（跨日身份与 lbc 真实验证）、Blocker 3（历史端点语义）、
  Blocker 6（legal-zero 正向确认）
- 无网络、无文件读写、无数据库、无缓存、无历史回填

## 3. Reused Final-snapshot Contract

输入必须是 Slice 2F producer 输出：

```text
schema_version == "short-term-limit-up-final-snapshot-v0.1"
```

每侧顶层字段集合精确等于（18 字段）：

```text
schema_version, requested_trade_date, observed_at, status, reason_codes,
session, is_final, finality_basis, required_observations,
completed_observations, stable_observation_count,
observation_interval_seconds, required_stability_window_seconds,
actual_stability_window_seconds, first_observation_monotonic,
last_observation_monotonic, snapshot, warnings
```

`type(result) is dict`（dict 子类不接受）；不得缺字段、不得有额外字段。
调用方构造的 `status="normal" / session="final" / is_final=true` 不得直接
视为可信，必须验证完整 producer 合同。

## 4. Public API

```python
SCHEMA_VERSION = "short-term-layered-promotion-coverage-gate-v0.1"
FINAL_SNAPSHOT_SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"

def evaluate_layered_promotion_coverage(
    previous_result: dict,
    current_result: dict,
) -> dict:
    ...
```

`__all__` 仅包含以上三个符号。公开 API 不接受 rates / candidate_rates /
computed_rates / status override / is_final override / coverage override /
implementation_allowed override / fetch function / clock / session 参数。

## 5. Strict Input Boundary

只接受精确内建 JSON 类型（None / bool / int / 有限 float / str / list /
dict），递归拒绝子类、tuple、set、bytes、complex、object()、NaN、
Infinity、-Infinity、非字符串 dict key。

顶层非精确 dict → `PREVIOUS_INPUT_INVALID` 或 `CURRENT_INPUT_INVALID`；
嵌套非法值同样属于对应侧 input invalid。普通异常结构化失败；
进程控制异常自然传播。

## 6. Producer Result Contract

每侧先验证（§7 任务合同）：

```text
schema_version == FINAL_SNAPSHOT_SCHEMA_VERSION
requested_trade_date: 严格合法 YYYY-MM-DD
observed_at: 非空可解析 UTC ISO
status: normal | partial | unavailable
reason_codes: list[str]
session: final | not_final
is_final: bool
finality_basis: str | null
required_observations: int > 0（bool 拒绝）
completed_observations: int，0..required
stable_observation_count: int，0..completed
observation_interval_seconds: 有限 float > 0
required_stability_window_seconds: 有限 float >= 0
actual_stability_window_seconds: 有限 float | null
first/last_observation_monotonic: 有限 float | null
snapshot: dict | null
warnings: list[str]
```

timing 关系：first/last 非空 → first <= last、actual 非空且
`actual == last - first`；first/last 均空 → actual 必须为空；
拒绝一侧空一侧非空。

## 7. Nested Adapter Contract

complete 侧的 `snapshot` 必须为 pool-adapter v0.1 完整合同（25 字段精确）：

```text
schema_version == "short-term-limit-up-pool-adapter-v0.1"
requested_trade_date == 外层 requested_trade_date
status == normal；reason_codes == []
transport_success / parse_success / required_field_present /
data_array_present / trade_date_match 均 is true
coverage_warning / upstream_null / unexplained_empty / legal_zero 均 is false
invalid_row_count / duplicate_code_count 为精确 int 0
row_count == len(rows)
source_pool_row_count == row_count + excluded_universe_count
error_class == "NONE"
```

本 gate 不正向接受 `legal_zero=true`（Blocker 6 仍 PARTIALLY CLOSED）。

非空目标池：rows 非空、target flag false。
目标 universe 过滤后为空：rows=[]、row_count=0、source>0、
excluded == source、target flag true、legal_zero=false——不等于全市场
legal zero。

rows：每行字段集合严格等于 `stock_code + lbc`；stock_code 严格六位数字
字符串；lbc type int > 0（bool 拒绝）；rows 按 stock_code 严格升序且唯一。
不得排序、去重或修正输入。

## 8. Complete Coverage

一侧满足以下全部条件才可归类 `complete`：

```text
status == normal；reason_codes == []
session == final；is_final is true
finality_basis == "three_identical_normal_observations"
required_observations == 3；completed_observations == 3
stable_observation_count == 3
first/last/actual 全部非空；actual + 1e-9 >= required_stability_window_seconds
snapshot 为精确 dict（nested adapter 完整合同）
warnings == []
```

任一 finality 不变量不满足 → 对应侧 `INPUT_INVALID`，不得降格为 complete。

## 9. Partial Coverage

一侧满足以下基本 producer failure 合同时归类 `partial`：

```text
status == partial；session == not_final；is_final is false
finality_basis is null；snapshot is null
reason_codes 非空 list[str] 且至少包含 SOURCE_PARTIAL
warnings 为 list[str]
```

若 status=partial 但同时 session=final / is_final=true / snapshot 非空 /
reason_codes=[] → input invalid，不得归类 partial。upstream producer 的
原始 reason code 不得原样透传到 gate 输出。

## 10. Unavailable Coverage

一侧满足以下基本 producer failure 合同时归类 `unavailable`：

```text
status == unavailable；session == not_final；is_final is false
finality_basis is null；snapshot is null
reason_codes 非空 list[str]，全部为非空 str、无重复
warnings 为 list[str]
```

不要求特定 producer reason code；未知 producer reason 不得进入 gate 输出。
unavailable 与 final/snapshot 非空组合 → input invalid。

## 11. Invalid Input

以下均属 input invalid（对应侧 `PREVIOUS/CURRENT_INPUT_INVALID`）：

```text
非 dict / dict 子类 / 缺字段 / 额外字段 / schema 错误 / status 非法
normal 但非 final / normal 但 snapshot=null
partial 但 snapshot 非空 / unavailable 但 final=true
reason_codes 类型错误 / 计数 bool、负数或越界
时钟 NaN / inf / 倒退 / timing 一侧为空
nested adapter 缺字段 / coverage_warning / legal_zero / unexplained_empty /
trade_date_match false/null / row_count 不一致 / source count 不守恒
非法 row / 未排序 / 重复代码
```

## 12. Date-order Boundary

两侧结构有效后：

```text
previous_result.requested_trade_date < current_result.requested_trade_date
```

只验证严格先后关系。日期严格递增不等于相邻交易日；不声称两日由可信
交易日历映射、历史端点语义已验证（Blocker 2 / 3 不推进）。

日期相等 / 逆序 / 不可解析 → 全局 invalid，`DATE_ORDER_INVALID`
（不可解析日期在 producer 合同层已判 input invalid，同样失败关闭）。

## 13. Reason-code Order

固定顺序（8 个，gate 层专属）：

```text
PREVIOUS_INPUT_INVALID
CURRENT_INPUT_INVALID
DATE_ORDER_INVALID
PREVIOUS_SOURCE_UNAVAILABLE
CURRENT_SOURCE_UNAVAILABLE
PREVIOUS_SOURCE_PARTIAL
CURRENT_SOURCE_PARTIAL
RATE_OUTPUT_SUPPRESSED
```

固定顺序、去重、未知 code 不输出。不得输出 upstream producer 原始
reason code。

## 14. Output Schema

所有普通返回路径字段集合精确等于（12 字段）：

```text
schema_version: str
status: complete | partial | unavailable | invalid
reason_codes: list[str]
coverage_eligible: bool
rates_policy: not_computed | must_be_null
layered_promotion_rates: null
previous_trade_date: str | null
current_trade_date: str | null
previous_state: complete | partial | unavailable | invalid
current_state: complete | partial | unavailable | invalid
implementation_allowed: false
warnings: list[str]
```

`layered_promotion_rates` 在本版本所有路径均为 null：

```text
complete:   coverage 合格，但生产计算尚未获授权，rates_policy=not_computed
partial/unavailable/invalid: 必须失败关闭，rates_policy=must_be_null
```

不得返回空列表冒充 null。

## 15. Fail-closed Invariants

```text
implementation_allowed is false
layered_promotion_rates is null

status != complete
  → coverage_eligible=false
  → rates_policy=must_be_null
  → RATE_OUTPUT_SUPPRESSED 在 reason_codes

status == complete
  → coverage_eligible=true
  → reason_codes=[]
  → rates_policy=not_computed
  → previous_state=current_state=complete
```

不得出现：partial + coverage_eligible=true、partial/unavailable/invalid +
concrete rates、complete + implementation_allowed=true、
complete + rates_policy=must_be_null。

## 16. Legal-zero Boundary

```text
legal_zero 正向确认未实现（Blocker 6 PARTIALLY CLOSED）
nested legal_zero=true: gate 拒绝（input invalid）
target-universe-empty: 允许 complete，但 legal_zero=false，不等于全市场 legal zero
```

## 17. Real Producer Joint Tests

正式测试通过真实
`short_term_limit_up_final_snapshot.fetch_final_limit_up_pool_snapshot`
组装输入（仅 fake pool adapter / trade calendar / sleep / monotonic，
无真实等待、无网络）：

```text
两侧真实 complete producer 输出 → gate complete
真实 producer partial 输出 → gate partial / suppressed
真实 producer unavailable 输出 → gate unavailable / suppressed
真实 target-universe-empty complete → gate complete
```

gate 模块本身不调用 producer；仅测试负责组装真实 producer 输出。

## 18. Blocker 8 Decision

**candidate CLOSED pending independent review**

关闭范围仅为：

```text
任何 partial、unavailable、invalid 或 coverage 不完整输入，
机械强制 rates=null，不允许近似值或部分值泄漏。
```

关闭条件全部满足：

```text
双侧 producer 合同严格验证
nested adapter coverage 严格验证
partial/unavailable 状态不可伪造 final
日期先后关系验证
失败状态 rates_policy=must_be_null
失败状态 layered_promotion_rates=null
complete 状态也不计算或透传 rates
普通异常失败关闭
进程控制异常自然传播
正式测试与独立补测全部通过
```

正式关闭由独立复审（审查者 C）确认后作出；Q 不得自行正式关闭。
Blocker 8 关闭不代表生产晋级率获准。

## 19. Remaining Blockers

| Blocker | 状态 | 说明 |
|---------|------|------|
| 1 | CLOSED | 沿用适配器结论 |
| 2 | OPEN | 相邻交易日跨日身份与 lbc 真实验证 |
| 3 | OPEN | 历史日期上游语义验证 |
| 4 | CLOSED_BY_NON_ADOPTION | getYesterdayZTPool 不采用 |
| 5 | CLOSED for T+1 completed-session snapshots | 沿用 Slice 2F |
| 6 | PARTIALLY CLOSED | legal-zero 正向确认未实现 |
| 7 | CLOSED | 沿用适配器 universe 合同 |
| 8 | candidate CLOSED pending independent review | 本 gate 范围 |
| 9 | CLOSED | 沿用 Slice 2G |

`implementation_allowed(layered_promotion_rates) = false`。

## 20. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- coverage eligibility gate 完整落地，partial/unavailable/invalid 强制
  rates=null
- 双侧 producer 合同与 nested adapter 覆盖严格验证
- complete 不计算、不接收、不透传 rates
- 普通异常失败关闭、进程控制异常自然传播、无生产接入

剩余阻断：

- Blocker 2 / 3 / 6 未关闭
- `layered_promotion_rates` 生产实现仍不允许
