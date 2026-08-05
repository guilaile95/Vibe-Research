# BK-11 fact compare calculator v0.1

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

- 对两份已批准 `short-term-daily-facts-v0.1` envelope（previous /
  current）做描述性聚合差异计算
- facts 段 14 字段数值 delta（null 安全）
- ladder 段 max_boards / lianban_count / 板级 count 分布变化
- gap 段缺口层级数 / 段数 / 最大宽度 / 首缺口 / 连续性对比
- 组合状态与固定 reason codes

### Non-goals（硬性）

```text
- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不计算次日收益 / premium / loss_effect（Slice 0 阻断范围）
- 不评估 legal-zero（Blocker 6）
- 不验证 consecutive lbc 来源语义
- 不依赖 live 外部数据 / 交易日历模块
- 不接入 API / 页面 / 数据库 / 调度器
```

## 3. Reused Contract

输入为两份 daily-facts envelope：

```text
schema_version == "short-term-daily-facts-v0.1"
```

15 字段精确集合；sections 精确 {facts, ladder, gap}。

## 4. Input Validation

```text
type(envelope) is dict（拒绝子类）
schema_version 精确匹配
15 字段精确集合
trade_date: 严格 YYYY-MM-DD 真实日历日期
session: 8 会话词表
status: normal / partial / unavailable / invalid
is_final: 严格 bool
source_ids: list[str]
sections: 精确 {facts, ladder, gap}
```

违反 -> `ENVELOPE_CONTRACT_INVALID` + `OUTPUT_SUPPRESSED`。

日期顺序：

```text
previous.trade_date < current.trade_date（严格递增）
相等 / 逆序 -> DATE_ORDER_INVALID + OUTPUT_SUPPRESSED
```

本模块不要求相邻交易日，也不声称相邻关系。

## 5. Facts Delta

对 Slice 1 全部 14 个事实字段：

```text
两侧均为严格 int  -> delta = curr - prev（int）
两侧均为有限数     -> delta = round4(curr - prev)（float）
任一为 None/非法   -> delta = null
```

字段列表：

```text
advance_count / decline_count / flat_count / suspended_count /
eligible_count / valid_count / up_ratio / limit_up_count /
limit_down_count / failed_limit_up_count / touched_limit_up_count /
sealed_limit_up_count / failed_board_rate / seal_rate
```

## 6. Ladder Delta

```text
prev/curr max_boards 与 max_boards_delta
prev/curr lianban_count 与 lianban_count_delta
prev/curr occupied_boards（升序）
board_level_changes: 两侧板级并集升序，
  {boards, prev_count, curr_count, delta}
```

任一侧 ladder section 缺失 -> delta=null、section_status=unavailable。

## 7. Gap Delta

```text
prev/curr gap_level_count / gap_segment_count / largest_gap_width 与 delta
prev/curr first_gap_board（int|null）
prev/curr is_continuous（bool）
```

## 8. Status and Reason Codes

固定 reason-code 顺序：

```text
INPUT_CONTRACT_INVALID
ENVELOPE_CONTRACT_INVALID
DATE_ORDER_INVALID
SOURCE_UNAVAILABLE
SOURCE_PARTIAL
OUTPUT_SUPPRESSED
```

状态优先级：

```text
normal(0) < partial(1) < unavailable(2) < invalid(3)
overall = envelope 状态与三 section 状态的最差者
```

映射：

```text
输入非 dict / 形状非法      -> invalid, ENVELOPE_CONTRACT_INVALID + SUPPRESSED
日期相等 / 逆序             -> invalid, DATE_ORDER_INVALID + SUPPRESSED
任一侧 envelope unavailable -> 至少 unavailable, SOURCE_UNAVAILABLE + SUPPRESSED
任一侧 envelope partial     -> 至少 partial, SOURCE_PARTIAL + SUPPRESSED
任一侧 envelope invalid     -> invalid, ENVELOPE_CONTRACT_INVALID + SUPPRESSED
section 缺失                -> 该 section unavailable（delta=null）
全部 normal                 -> normal, []
```

## 9. Section Availability

```text
facts: daily-facts 恒存在；envelope partial 时仍逐字段 null 安全计算
ladder: 任一侧缺失 -> delta=null
gap: 任一侧缺失 -> delta=null
```

## 10. Examples

```text
prev: limit_up_count=10, max_boards=4, gap_level_count=1
curr: limit_up_count=15, max_boards=5, gap_level_count=0
-> facts.limit_up_count_delta=5
-> ladder.max_boards_delta=1, lianban_count_delta=2,
   board_level_changes=[{2,+1},{4,0},{5,+1}]
-> gap.gap_level_count_delta=-1, is_continuous true<-false
```

## 11. Exception Boundary

```text
公共入口只捕获 except Exception
普通异常 -> 固定 invalid envelope（INPUT_CONTRACT_INVALID +
  OUTPUT_SUPPRESSED，deltas 全 null）
emergency fallback 直接构造完整固定字面量，零业务 helper、
  零输入读取、零异常文本
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

## 12. Input Immutability

```text
调用前后两份输入深度相等
输出与输入不共享可变引用（board_level_changes 为新列表）
```

## 13. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_fact_compare.py`）：

```text
公开合同 / facts 全量 delta / null 字段 / 浮点精度
ladder 板级变化 / gap 全量 delta / section 缺失
日期相等 / 逆序 / 状态组合（partial/unavailable/invalid 优先级）
输入合同（非 dict / schema / 字段集合 / 日期 / session）
输出合同（limitations 固定 / 日期复制）
输入不可变 / 引用隔离 / 跨调用隔离
普通异常固定 fallback（5 helper x 3 异常类型）
进程控制异常传播
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 14. Limitations

```text
1. 描述性聚合差异，不进行逐股跨日身份追踪
2. 不验证 consecutive lbc 来源语义
3. 不要求相邻交易日（调用方负责锚点语义）
4. 不计算晋级率 / 收益 / 溢价 / 亏钱效应
5. 不接入生产页面 / API / 调度器
```

## 15. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- delta 数学机械可复算
- 组合状态与 reason codes 固定
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称页面/API 已完成
```
