# BK-11 daily-facts composition layer v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | GO for pure calculator candidate |
| calculator candidate | 通过（纯计算、确定性、失败关闭） |
| production integration | not authorized |
| Blocker 2 | OPEN（未评估/未改变） |
| Blocker 3 | OPEN（未评估/未改变） |
| Blocker 6 | PARTIALLY CLOSED（未评估/未改变） |
| implementation_allowed(layered_promotion_rates) | false |

本模块不宣称 BK-11 Slice 2 全部完成，不宣称 Blocker 2/3/6 已关闭，
不宣称 layered_promotion_rates 可实现，不宣称页面或 API 已完成。

## 2. Scope and Non-goals

### Scope

- 基于已批准的 Slice 2F final-snapshot producer envelope 与 Slice 1
  市场事实输入组件（breadth / limit_activity / facts_data_health），
  编排三个已批准纯计算器，产出单日组合 envelope
- sections 精确包含 facts / ladder / gap 三个已批准 envelope
- 顶层提供组合状态、组合 reason codes 与 producer 元数据（单日权威）

### Non-goals

- 不计算 layered_promotion_rates
- 不验证 consecutive lbc 来源语义（adapter lbc ->
  ladder consecutive_limit_up_days 仅为机械字段映射）
- 不评估 legal-zero 正向来源证明
- 不接入 API / 页面 / 数据库 / 调度器
- 不依赖 live 外部数据
- 不修改任何既有已批准模块

## 3. Reused Contracts

输入组合 envelope：

```text
final_snapshot:    Slice 2F producer envelope（18 字段）
breadth:           Slice 1 市场宽度原始计数（5 字段）
limit_activity:    Slice 1 涨跌停/炸板原始计数（3 字段）
facts_data_health: Slice 1 Data Health（10 字段）
```

编排的已批准纯计算器：

```text
compute_limit_up_ladder           (Slice 2A, short-term-limit-up-ladder-v0.1)
compute_ladder_gap                (Slice 2J, short-term-ladder-gap-v0.1)
compute_short_term_market_facts   (Slice 1, short-term-market-facts-v0.1)
```

## 4. Input Validation

### 组合输入合同

```text
type(input) is dict（拒绝子类）
4 个键必须全部存在：final_snapshot / breadth / limit_activity /
  facts_data_health
额外键忽略
```

违反 -> `INPUT_CONTRACT_INVALID` + `OUTPUT_SUPPRESSED`。

### producer envelope 合同（对齐 Slice 2H）

```text
schema_version == "short-term-limit-up-final-snapshot-v0.1"
精确 18 字段集合
requested_trade_date: 严格 YYYY-MM-DD 真实日历日期
observed_at: 必填，合法 UTC ISO 8601（非 null、前后空白拒绝）
status: normal / partial / unavailable
reason_codes: 精确 list[str]、非空字符串
session: final / not_final（producer 词表）
is_final: 严格 bool，与 session=="final" 一致
finality 计数与 timing 关系严格校验
partial / unavailable: snapshot 必须为 null、reason_codes 非空
```

违反 -> `PRODUCER_CONTRACT_INVALID` + `OUTPUT_SUPPRESSED`。

### complete-side 不变量（producer normal）

```text
status=normal, reason_codes=[]
session=final, is_final=true
finality_basis="three_identical_normal_observations"
required=3, completed=3, stable=3
interval==2.2, required_window==4.4
first/last/actual 非空且 actual+1e-9 >= 4.4
warnings==[]
nested adapter 25 字段完整合同（rows 严格升序唯一，
  {stock_code 六位, lbc 严格 int>0}，observed_at 必填非 null，
  计数守恒）
```

任一不满足 -> `PRODUCER_CONTRACT_INVALID`。

## 5. Composition

```text
facts section: 始终计算（独立于 producer 状态）
  facts_snapshot 元数据取自 producer（单日权威），
  breadth / limit_activity / facts_data_health 透传

ladder section: 仅 producer normal（complete-side）时计算
  ladder_snapshot:
    source_ids = [adapter source_id]
    fetched_at = adapter observed_at
    snapshot_at = producer observed_at
    data_health = adapter 10 字段子集
    limit_up_pool = adapter rows 机械映射
      {stock_code, consecutive_limit_up_days = lbc}

gap section: ladder envelope 存在时计算（2J 自身处理抑制）
```

producer 非 normal 时 ladder/gap section 为 null，顶层 reason codes
携带 `UPSTREAM_LADDER_PARTIAL` / `UPSTREAM_LADDER_UNAVAILABLE`。

## 6. Metadata Mapping

```text
producer 元数据为单日权威（trade_date / session / is_final /
source_ids / fetched_at / snapshot_at）

session 词表映射（组合 envelope 使用 8 会话词表）:
  producer "final"      -> "final"
  producer "not_final"  -> "unavailable"
  （原值保留于 source_status；信息不丢失）

source_ids:
  producer normal -> [adapter source_id]
  其他             -> []

fetched_at = snapshot_at = producer observed_at
```

## 7. Output Schema

输出 envelope 精确包含 15 个字段：

```text
schema_version, trade_date, session, is_final, source_ids,
fetched_at, snapshot_at, status, reason_codes, warnings,
limitations, source_schema_version, source_status,
source_reason_codes, sections
```

`sections` 精确包含 3 个键：

```text
facts:  Slice 1 envelope（始终存在）
ladder: Slice 2A envelope（producer normal 时存在，否则 null）
gap:    Slice 2J envelope（ladder 存在时存在，否则 null）
```

固定 limitations（每次新建字面量）：

```text
composed from approved BK-11 pure calculators
does not validate upstream consecutive-limit-up semantics
does not compute layered promotion rates
production integration not authorized
```

## 8. Status and Reason Codes

组合状态优先级：

```text
normal(0) < partial(1) < unavailable(2) < invalid(3)
status = 所有 section 状态 + producer 状态（非 normal 时）的最差者
```

固定 reason-code 顺序：

```text
INPUT_CONTRACT_INVALID
PRODUCER_CONTRACT_INVALID
UPSTREAM_LADDER_UNAVAILABLE
UPSTREAM_LADDER_PARTIAL
OUTPUT_SUPPRESSED
```

映射：

```text
输入合同非法      -> invalid, [INPUT_CONTRACT_INVALID, OUTPUT_SUPPRESSED]
producer 合同非法 -> invalid, [PRODUCER_CONTRACT_INVALID, OUTPUT_SUPPRESSED]
producer partial  -> 至少 partial, [UPSTREAM_LADDER_PARTIAL, OUTPUT_SUPPRESSED]
producer unavailable -> 至少 unavailable,
                        [UPSTREAM_LADDER_UNAVAILABLE, OUTPUT_SUPPRESSED]
任一 section 非 normal -> OUTPUT_SUPPRESSED
全部 normal      -> normal, []
```

section 自身状态与 reason codes 保留在各 section envelope 内，不提升。

## 9. Boundary Semantics

```text
target-universe-empty adapter（rows=[]）:
  adapter 合同禁止 legal_zero=true（Blocker 6 未实现正向确认）
  -> 2A 判 LIMIT_UP_POOL_UNAVAILABLE
  -> ladder section unavailable、gap section suppressed envelope
  -> 组合至少 unavailable

huge lbc（如 10**30）:
  adapter 合同允许任意正 int lbc
  -> 2A ladder normal（无界安全）
  -> 2J gap invalid（板级上限 1000）
  -> 组合 invalid + OUTPUT_SUPPRESSED（gap section 携带细节）
```

## 10. Examples

```text
全 normal：
  sections.facts=normal, sections.ladder=normal, sections.gap=normal
  status=normal, reason_codes=[]

producer partial + facts normal：
  ladder/gap=null, status=partial,
  reason_codes=[UPSTREAM_LADDER_PARTIAL, OUTPUT_SUPPRESSED]

producer normal + facts coverage_warning：
  sections 全部存在, facts=partial,
  status=partial, reason_codes=[OUTPUT_SUPPRESSED]
```

## 11. Exception Boundary

```text
公共入口只捕获 except Exception
普通异常 -> 固定 invalid envelope（INPUT_CONTRACT_INVALID +
  OUTPUT_SUPPRESSED，sections 全 null）
emergency fallback 直接构造完整固定字面量，零业务 helper 调用、
  零输入读取、零异常文本
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

## 12. Input Immutability

```text
调用前后输入深度相等
输出与输入不共享可变引用（sections 为新构造 envelope）
```

## 13. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_daily_facts.py`）：

```text
公开合同 / 全 normal 组合 / 高板断层派生
target-universe-empty -> ladder unavailable、gap suppressed
producer partial/unavailable 抑制（ladder/gap=null）
状态优先级组合（facts unavailable > producer partial 等）
breadth 非法 -> facts partial
huge lbc -> gap section invalid、组合 invalid
输入合同缺失键/非 dict/子类
producer 合同（schema/字段/日期/时间戳/形状/complete-side/adapter）
输出 schema / section schema / 元数据复制
输入不可变 / 引用隔离 / 跨调用隔离
普通异常固定 fallback（5 helper x RuntimeError/ValueError/TypeError）
导入计算器抛异常 -> 固定 fallback
进程控制异常传播
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 14. Limitations

```text
1. 组合依赖三个已批准纯计算器的正确性
2. adapter lbc -> consecutive_limit_up_days 为机械字段映射，
   不验证连续板来源语义（Blocker 2 不动）
3. 不评估 legal-zero 正向来源（Blocker 6 不动）
4. 不计算晋级率（layered_promotion_rates 恒未实现）
5. 不接入生产页面 / API / 调度器
6. producer 元数据为单日权威；facts 组件不携带独立元数据
7. session "not_final" 映射为 "unavailable"（组合词表）
```

## 15. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- 编排三个已批准计算器，sections 保留各自完整 envelope
- 组合状态优先级与 reason codes 机械可复算
- 普通异常固定 fallback，进程控制异常自然传播
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称 Slice 2 全部完成或页面/API 已完成
```
