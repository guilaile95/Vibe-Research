# BK-11 fact summary calculator v0.1

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

本模块不宣称 Blocker 2/3/6 已关闭，不宣称 layered_promotion_rates
可实现，不宣称页面或 API 已完成。

## 2. Scope and Non-goals

### Scope

- 接收已批准 `short-term-daily-facts-v0.1` envelope 列表
- 输出窗口内描述性摘要：窗口信息、状态分布、关键事实统计、
  梯队统计、断层统计
- 统计只覆盖 envelope status == normal 的天

### Non-goals（硬性）

```text
- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不计算次日收益 / premium / loss_effect
- 不评估 legal zero（Blocker 6）
- 不验证 consecutive lbc 来源语义
- 不依赖存储 / 数据库 / live 外部数据（调用方传入内存列表）
- 不接入 API / 页面 / 调度器
```

## 3. Reused Contract

输入为 daily-facts envelope 列表：

```text
schema_version == "short-term-daily-facts-v0.1"
15 字段精确集合；sections 精确 {facts, ladder, gap}
```

## 4. Window Contract

```text
type(envelopes) is list，非空
每项 envelope 形状校验（15 字段 / schema / 真实日期 / 8 会话 /
  4 状态 / is_final / source_ids / sections）
按 (trade_date, session) 严格升序（字典序，与时间序一致）
(trade_date, session) 无重复
```

违反：

```text
非 list / 空列表        -> INPUT_CONTRACT_INVALID + OUTPUT_SUPPRESSED
任一 envelope 形状非法  -> ENVELOPE_CONTRACT_INVALID + OUTPUT_SUPPRESSED
重复快照                -> DUPLICATE_SNAPSHOT_INVALID + OUTPUT_SUPPRESSED
未按序排列              -> DATE_ORDER_INVALID + OUTPUT_SUPPRESSED
窗口含 invalid 状态 envelope -> invalid（该日数据不可用，窗口失败关闭）
```

## 5. Stats Scope

```text
统计只覆盖 envelope status == normal 的天
partial / unavailable / invalid 仅计入 status_distribution
```

### facts（5 个字段）

```text
int 字段: limit_up_count, advance_count
  -> min / max 为 int，avg = round4(sum/count)
float 字段: failed_board_rate, seal_rate, up_ratio
  -> min / max / avg 均 round4
每字段 count = 贡献天数；字段值为 None/非法 -> 跳过
```

### ladder

```text
max_boards: min / max / avg / count（int 字段）
lianban_count: min / max / avg / count
days_with_ladder = 出现有效 max_boards 的天数
```

### gap

```text
gap_level_count / largest_gap_width: min / max / avg / count
days_with_gap_section = 出现有效 gap_level_count 的天数
continuous_days = is_continuous=true 的天数
```

## 6. Output Schema

```text
schema_version
window: {count, first_trade_date, last_trade_date}
status
reason_codes
warnings
limitations
stats: {
  status_distribution: {normal, partial, unavailable, invalid},
  facts: {limit_up_count, advance_count, failed_board_rate,
          seal_rate, up_ratio} 各 {min, max, avg, count},
  ladder: {max_boards, lianban_count, days_with_ladder},
  gap: {gap_level_count, largest_gap_width,
        days_with_gap_section, continuous_days},
}
```

固定 limitations：

```text
descriptive window summary of daily-facts envelopes
stats computed over normal-status days only
does not compute layered promotion rates
does not validate consecutive-limit-up semantics
no per-stock cross-day identity tracking
does not evaluate legal zero
```

## 7. Status and Reason Codes

固定 reason-code 顺序：

```text
INPUT_CONTRACT_INVALID
ENVELOPE_CONTRACT_INVALID
DUPLICATE_SNAPSHOT_INVALID
DATE_ORDER_INVALID
SOURCE_UNAVAILABLE
SOURCE_PARTIAL
OUTPUT_SUPPRESSED
```

映射：

```text
全部 normal           -> status=normal, reason_codes=[]
含 partial（无 unavailable）-> partial, [SOURCE_PARTIAL, OUTPUT_SUPPRESSED]
含 unavailable         -> unavailable, [SOURCE_UNAVAILABLE, OUTPUT_SUPPRESSED]
含 invalid 状态 envelope -> invalid, [ENVELOPE_CONTRACT_INVALID,
  OUTPUT_SUPPRESSED]
```

## 8. Examples

```text
3 天窗口（全部 normal）:
  limit_up_count = 8 / 12 / 10 -> {min:8, max:12, avg:10.0, count:3}
  max_boards = 2 / 4 / 5 -> {min:2, max:5, avg:3.6667, count:3}
  gap_level_count = 0 / 1 / 0 -> {min:0, max:1, avg:0.3333, count:3}
  continuous_days = 2

2 天窗口（1 normal + 1 partial）:
  status=partial；limit_up_count 统计只含 normal 天
```

## 9. Exception Boundary

```text
公共入口只捕获 except Exception
普通异常 -> 固定 invalid envelope（INPUT_CONTRACT_INVALID +
  OUTPUT_SUPPRESSED，stats=null）
emergency fallback 直接构造完整固定字面量，零业务 helper、
  零输入读取、零异常文本
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

## 10. Input Immutability

```text
调用前后输入列表与各 envelope 深度相等
输出与输入不共享可变引用
```

## 11. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_fact_summary.py`）：

```text
公开合同 / facts 统计数学（int/float 字段 min/max/avg/count）
ladder / gap 统计 / null 字段跳过 / section 缺失
状态分布（partial 天不计入统计）
窗口合同（非 list / 空 / 重复 / 未排序 / schema / sections 缺失）
输出合同（limitations 固定 / 窗口信息）
输入不可变 / 引用隔离 / 跨调用隔离
普通异常固定 fallback（5 helper x 3 异常类型）
进程控制异常传播
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 12. Limitations

```text
1. 描述性窗口摘要，统计只覆盖 normal 天
2. 不进行逐股跨日身份追踪 / 晋级率
3. 不验证 consecutive lbc 来源语义
4. 输入必须已按 (trade_date, session) 排序且无重复（调用方负责）
5. 不接入生产页面 / API / 调度器
```

## 13. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- 统计数学机械可复算
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称页面/API 已完成
```
