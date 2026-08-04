# BK-11 layered-promotion fixture、reason-code 与状态映射机械验证器 v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 5 | CLOSED for T+1 completed-session snapshots（沿用 Slice 2F） |
| Blocker 6 | PARTIALLY CLOSED |
| Blocker 7 | CLOSED（沿用适配器 universe 合同） |
| Blocker 8 | OPEN |
| Blocker 9 | candidate CLOSED — 真实 fixture、变异测试与机械扫描全部通过后成立 |
| implementation_allowed(layered_promotion_rates) | false |

Blocker 9 关闭不等于允许生产 `layered_promotion_rates` 实现。
Blocker 2 / 3 / 6 / 8 仍阻断生产实现。

## 2. Scope and Non-goals

### Scope

- 纯离线、纯确定性机械验证器：合成 fixture 与已批准合同的逐项一致性检查
- 固定 19 个 issue code、12 个 reason code 与固定顺序
- 独立离线 oracle：从 previous/current snapshot + data_health 推导
  status / reason codes / rates，再与 expected 精确比较
- 真实 fixture 文件验证 + 变异测试矩阵

### Non-goals

- 不是生产 `layered_promotion_rates` 实现；不得被 market.py / app.py /
  调度器 / API / 生产决策链引用
- 不做真实行情网络请求、历史回填、缓存、数据库写入
- 不重新关闭 Blocker 5；不推进 Blocker 2 / 3 / 6 / 8
- 不通过股票名称判断 ST/\*ST；不把代码前缀当完整 universe 规则

## 3. Input Fixture

输入为已解析的 dict（由测试或一次性脚本从
`docs/research/BK11_LAYERED_PROMOTION_FIXTURE_V01.json` 读取）。

生产函数不自行读取文件；仅允许 Python 标准库；
不得导入 astock / trade_calendar / pool adapter / final producer /
requests / httpx / akshare / pandas / numpy。

## 4. Public API

```python
SCHEMA_VERSION = "short-term-layered-promotion-contract-validator-v0.1"
FIXTURE_SCHEMA_VERSION = "bk11-layered-promotion-fixture.v0.1"

def validate_layered_promotion_fixture(fixture: dict) -> dict:
    ...
```

`__all__` 仅包含以上三个符号。公开函数不接受文件路径、网络、live、
final producer、计算服务或调用方 override 参数。

输出合同：

```text
schema_version: str
fixture_schema_version: str | null
status: valid | invalid
issue_codes: list[str]
issue_count: non-negative int
case_count: non-negative int
validated_case_ids: list[str]
case_results: list[dict]
warnings: list[str]
```

成功：`status=valid`、`issue_codes=[]`、`issue_count=0`、`case_count=7`、
`validated_case_ids` 为 7 个 case ID、`warnings=[]`。

## 5. Top-level Fixture Contract

顶层字段集合严格等于：

```text
schema_version, fixture_kind, generated_at, description, trade_dates,
market_scope, code_prefix_contract, cases
```

要求：

```text
schema_version == "bk11-layered-promotion-fixture.v0.1"
fixture_kind == "synthetic-normalized"
generated_at: 非空可解析 UTC ISO 时间（offset 为零）
description: 非空字符串且明确 synthetic（含 "synthetic"）
trade_dates: 恰两个严格合法 YYYY-MM-DD，previous < current
cases: 非空 list
```

不得接受：bool 冒充 int、NaN、Infinity、非 JSON 值（object/set/bytes 等）、
额外顶层字段、缺少顶层字段。fixture 输入不得被修改。

## 6. Market Scope and Prefix Contract

`included` 必须精确表达：

```text
SH main, SZ main, ChiNext, STAR, ST, *ST
```

`excluded` 必须精确表达：

```text
BSE, IPO no-limit period, delisting period, B shares, ETF, LOF,
convertible bonds, funds, indexes
```

要求：均为 list[str]、无重复、无空字符串；ST 与 \*ST 必须 included；
BSE 必须 excluded。不得通过股票名称判断 ST/\*ST。

正常合成样本股票代码仅允许 `60xxxx / 00xxxx / 30xxxx / 68xxxx`；
排除形状 `4xxxxx / 8xxxxx / 920xxx / 9xxxxx`。前缀规则只用于 synthetic
fixture 形状校验，不声称可完整决定生产 universe。

## 7. Case-set Contract

case ID 必须精确为（顺序一致、恰 7 个、无重复）：

```text
normal, zero_denominator, previous_legal_zero, current_legal_zero,
partial, unavailable, identity_edge
```

每个 case 必须包含：

```text
case_id, case_name, description, previous_trade_date, current_trade_date,
previous_snapshot, current_snapshot, expected
```

日期：严格合法 YYYY-MM-DD；previous < current；与顶层 trade_dates 一致。

## 8. Snapshot Contract

每个 previous/current snapshot 字段集合严格等于：

```text
trade_date, session, is_final, source_ids, fetched_at, snapshot_at,
limit_up_pool, data_health
```

要求：

```text
trade_date 与 case 侧别日期一致
session == "final"
is_final is true
source_ids: 非空 list[str]
fetched_at / snapshot_at: 可解析 UTC ISO，fetched_at <= snapshot_at
limit_up_pool: list
data_health: dict
```

`session="final"` / `is_final=true` 只验证 synthetic fixture 的合同形状，
不解释为生产来源已可信，不重新关闭 Blocker 5。

## 9. Data-health Contract

data_health 字段集合严格等于：

```text
transport_success, parse_success, required_field_present, data_array_present,
trade_date_match, row_count, legal_zero, upstream_null, unexplained_empty,
coverage_warning
```

类型：8 个 bool 字段身份判断；`trade_date_match` 为 True/False/None 身份判断
（1/0 不得冒充）；`row_count` 非负 int（bool 拒绝）。

基本不变量：

```text
row_count == len(limit_up_pool)
legal_zero=true → row_count=0
unexplained_empty=true → row_count=0
legal_zero=true 与 unexplained_empty=true 不得同时成立
```

## 10. Expected-output Contract

expected 字段集合严格等于：

```text
status, reason_codes, warnings, layered_promotion_rates
```

```text
status: normal | partial | unavailable
reason_codes: list[str]，固定集合、固定顺序、无重复
warnings: list[str]
rates: normal → list；partial/unavailable → null
```

不得接受：partial/unavailable + concrete rates；normal + null。

## 11. Reason-code Order

固定顺序：

```text
SOURCE_UNAVAILABLE, PREVIOUS_SNAPSHOT_UNAVAILABLE,
CURRENT_SNAPSHOT_UNAVAILABLE, TRADING_CALENDAR_UNAVAILABLE,
TRADE_DATE_MISMATCH, NOT_FINAL, SOURCE_PARTIAL, PARTIAL_COVERAGE,
IDENTITY_MATCH_INCOMPLETE, INVALID_POOL_ROW, DUPLICATE_STOCK_CODE,
UNEXPLAINED_EMPTY
```

未知 code 拒绝、重复拒绝、顺序错误拒绝。本轮不增加新 reason code。

## 12. Offline Oracle

验证器不信任 fixture 的 expected 数值，从 previous/current snapshot 与
data_health 独立推导：

```text
derived_status
derived_reason_codes
derived_layered_promotion_rates
```

推导优先级：

```text
1. fixture/case/snapshot schema invalid（case invalid）
2. unavailable 来源失败（SOURCE_UNAVAILABLE + 侧别码）
3. trade-date mismatch（TRADE_DATE_MISMATCH）
4. not final（本 fixture 合同要求 final 形状，非 final 属 schema 无效）
5. partial coverage（SOURCE_PARTIAL + PARTIAL_COVERAGE）
6. previous legal zero
7. current legal zero
8. normal calculation
```

legal_zero / partial / normal calculation 不得覆盖更高优先级的
unavailable 条件。

## 13. Normal Calculation Contract

对每个 `N >= 1`：

```text
denominator_N = previous final pool 中 consecutive_limit_up_days == N
               的唯一股票数
numerator_N   = 上述股票中，在 current final pool 出现且
               consecutive_limit_up_days == N + 1 的唯一股票数
```

只输出 denominator > 0 的昨日实际层级，按 from_level 升序；
`to_level = from_level + 1`；`sample_count = denominator`；
`rate = round(numerator / denominator, 4)`。

rate item 字段集合严格等于：

```text
from_level, to_level, numerator, denominator, sample_count, rate
```

类型：from_level int>=1（bool 拒绝）；to_level == from_level+1；
numerator int>=0；denominator int>0；sample_count == denominator；
rate 有限且 `0.0 <= rate <= 1.0` 且等于 `round(numerator/denominator, 4)`。
不得输出 denominator=0 的空层。

## 14. Legal-zero Cases

```text
previous legal zero: derived_status=normal, reason_codes=[],
  rates=[]

current legal zero: derived_status=normal, reason_codes=[],
  昨日每个实际层级均输出，numerator=0，rate=0.0
```

## 15. Partial and Unavailable Mapping

任一侧 `coverage_warning=true` 或 `unexplained_empty=true`：

```text
derived_status=partial
derived_layered_promotion_rates=null
reason_codes 包含 SOURCE_PARTIAL + PARTIAL_COVERAGE
```

来源全局失败 / 日期不匹配 / 非 final：

```text
derived_status=unavailable
derived_layered_promotion_rates=null
按侧别输出 SOURCE_UNAVAILABLE + PREVIOUS/CURRENT_SNAPSHOT_UNAVAILABLE，
或 TRADE_DATE_MISMATCH / NOT_FINAL
```

不得利用合法行继续计算近似比例。

## 16. Identity-edge Rules

缺失、未递增、跳级均不算晋级。只有同一 stock_code 且 `N → N+1`
才计入 numerator。

identity-edge fixture 本身若含重复或非法行 → case invalid
（POOL_ROW_INVALID），不得称其为 normal。

## 17. Mutation-test Matrix

对真实 fixture 深拷贝后的最小修改，每项必须 `status=invalid` 且
`issue_codes` 含对应固定 code：

| 变异 | issue code |
|------|-----------|
| 错误 schema_version | FIXTURE_SCHEMA_INVALID |
| 错误 fixture_kind / 缺顶层字段 / 额外顶层字段 / 日期关系错误 | TOP_LEVEL_FIELD_INVALID |
| ST 删除 / BSE 删除 / 重复或空字符串成员 | MARKET_SCOPE_INVALID |
| 重复 case_id | DUPLICATE_CASE_ID |
| 缺 case / 未知 case / case 顺序错误 | CASE_SET_INVALID |
| case 日期关系 / 与顶层不一致 | CASE_SCHEMA_INVALID |
| snapshot 缺字段 / 日期错 / 非 final / 时间序错 | SNAPSHOT_SCHEMA_INVALID |
| data_health 缺字段 / row_count 不一致 / 双 true / bool 冒充 | DATA_HEALTH_INVALID |
| 非法前缀 / 重复代码 / 未排序 / lbc 非法 / 额外字段 | POOL_ROW_INVALID |
| partial/unavailable + concrete rates / normal + null | EXPECTED_SCHEMA_INVALID |
| 未知 status | EXPECTED_STATUS_INVALID |
| 未知 / 重复 reason code | REASON_CODE_INVALID |
| reason code 顺序错误 | REASON_CODE_ORDER_INVALID |
| numerator/denominator/跳级晋级错误 | RATE_CALCULATION_MISMATCH |
| sample_count / rate / to_level / 零分母层错误 | RATE_SCHEMA_INVALID |
| expected status/reason 与推导不一致 | STATUS_MAPPING_MISMATCH |

## 18. Mechanical Validation Results

- 真实 fixture：`status=valid`、`issue_codes=[]`、`issue_count=0`、
  `case_count=7`、7 个 case 全部 valid
- 变异测试：覆盖顶层 / market scope / case 集合 / snapshot /
  data health / reason code / rates / status mapping / identity edge
- fixture 修正披露：原 fixture 的 pool 行按层数分组排列而非按
  stock_code 严格升序（合同 §8 要求严格升序）；已按升序重排各行
  （仅重排行序，不改变任何计算）；无其他 fixture 内容变化

## 19. Blocker 9 Decision

**candidate CLOSED**

关闭条件全部满足：

```text
真实 fixture JSON 可解析
顶层合同通过
market scope 通过
7 个 case 集合通过
snapshot/data-health 通过
expected schema 通过
reason-code 固定集合和顺序通过
离线 oracle 与 expected 完全一致
partial/unavailable rates=null
mutation tests 全部通过
文档扫描无失真肯定性合同
普通异常失败关闭
进程控制异常自然传播
```

Blocker 9 关闭不代表生产 `layered_promotion_rates` 已获授权；
Blocker 2 / 3 / 6 / 8 仍阻断生产实现。

## 20. Remaining Blockers

| Blocker | 状态 | 说明 |
|---------|------|------|
| 1 | CLOSED | 沿用适配器结论 |
| 2 | OPEN | 相邻交易日 live 跨日身份与 lbc 探针 |
| 3 | OPEN | getTopicZTPool 历史日期上游语义验证 |
| 4 | CLOSED_BY_NON_ADOPTION | getYesterdayZTPool 不采用 |
| 5 | CLOSED for T+1 completed-session snapshots | 沿用 Slice 2F |
| 6 | PARTIALLY CLOSED | legal-zero 正向确认未实现 |
| 7 | CLOSED | 沿用适配器 universe 合同 |
| 8 | OPEN | partial rates=null 生产 gate |
| 9 | candidate CLOSED | 本验证器范围 |

`implementation_allowed(layered_promotion_rates) = false`。

## 21. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- 机械验证器完整落地，真实 fixture 与变异测试全部通过
- 离线 oracle 独立推导，expected 数值不受信任
- 固定 issue/reason code 集合与顺序，普通异常失败关闭
- 无新增依赖、不修改既有模块、无生产接入

剩余阻断：

- Blocker 2 / 3 / 6 / 8 未关闭
- `layered_promotion_rates` 生产实现仍不允许
