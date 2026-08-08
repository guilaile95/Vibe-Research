# BK-11 ladder gap calculator v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | GO for pure calculator candidate |
| calculator candidate | 通过（纯计算、确定性、失败关闭） |
| production integration | not authorized |
| Blocker 2 | 未评估（本轮不涉及） |
| Blocker 3 | 未评估（本轮不涉及） |
| Blocker 6 | 未评估（本轮不涉及） |
| implementation_allowed(layered_promotion_rates) | false |

本模块不宣称 BK-11 Slice 2 全部完成，不宣称 Blocker 2/3/6 已关闭，
不宣称 layered_promotion_rates 可实现，不宣称页面或 API 已完成。

## 2. Scope and Non-goals

### Scope

- 基于已批准的 `short-term-limit-up-ladder-v0.1` 输出 envelope，
  计算 2 板至 max_boards 之间缺失的整数板级和连续缺口区间
- 严格验证上游合同、元数据、状态与 reason codes
- 纯计算、确定性、失败关闭、输入不可变

### Non-goals

- 不处理 layered_promotion_rates
- 不进行跨日 lbc 验证
- 不依赖同花顺替代来源
- 不验证历史日期绑定
- 不进行 legal-zero 正向来源证明
- 不计算连板溢价 / 亏钱效应 / 题材结构
- 不接入 API / 页面 / 数据库 / 调度器
- 不验证上游 consecutive lbc 的来源语义

## 3. Reused Ladder Contract

输入必须是 Slice 2A 已批准的 ladder envelope：

```text
schema_version == "short-term-limit-up-ladder-v0.1"
```

必须读取并验证的 10 个字段：

```text
schema_version, trade_date, session, is_final, source_ids,
fetched_at, snapshot_at, status, reason_codes, metrics
```

额外的 envelope 字段（含调用方提供的 gap / missing_boards /
is_continuous / gap_segments）一律忽略，不透传、不参与计算。

上游 `status` 只允许 `normal` / `partial` / `unavailable`。

## 4. Input Validation

### envelope 基本合同

```text
type(envelope) is dict（拒绝子类）
schema_version 精确匹配上游版本
10 个字段必须全部存在
status 属于合法集合
reason_codes 为精确 list[str]（拒绝子类、空字符串），去重保序
metrics 为精确 dict，键集合精确等于
  {max_boards, lianban_count, ladder}
```

任何违反 -> `LADDER_CONTRACT_INVALID` + `GAP_OUTPUT_SUPPRESSED`。

### normal 状态上游 metrics 严格验证

```text
max_boards: 严格 int（拒绝 bool/float/str），0 <= max_boards <= 1000
lianban_count: 严格 int，>= 0
ladder: 精确 list；每项精确 dict，精确字段 boards/count
boards: 严格 int，2 <= boards <= 1000
count: 严格 int，> 0
ladder 按 boards 严格升序、boards 不重复
len(ladder) <= 999（合法层级域 2..1000 最多 999 个唯一层级）
sum(ladder[].count) == lianban_count

lianban_count > 0:
  ladder 非空
  max_boards == ladder[-1].boards

lianban_count == 0:
  ladder == []
  max_boards 只允许 0 或 1
```

以下均为合同非法：

```text
max_boards >= 2 但 ladder 为空
ladder 非空但 lianban_count=0
ladder 最大层与 max_boards 不一致
count 总和与 lianban_count 不一致
字段子类伪装 / 额外字段 / 缺失字段
未排序 / 重复层级 / boards < 2 / count <= 0
max_boards > 1000 / boards > 1000 / ladder 长度 > 999
```

### 板级安全上限（P1 修正）

```text
_MAX_BOARD_LEVEL = 1000
```

该值是纯计算资源安全上限，不是对 A 股历史最高连板数的业务判断。

超限输入必须在进入 gap 计算前固定返回 invalid：

```text
max_boards = 1001        -> invalid
max_boards = 10**30      -> invalid（不得调用 range(2, 超限值)）
boards = 1001            -> invalid
boards = 10**30          -> invalid
ladder 长度 > 999        -> invalid
```

不得截断 max_boards、不得把 1001 修正为 1000、不得部分计算、
不得依赖 MemoryError / OverflowError fail-close。

边界值必须允许：

```text
max_boards = 1000
ladder 最后一层 boards = 1000

max_boards=1000, ladder=[{"boards":1000,"count":1}]:
  missing_boards = 2..999
  单一 gap segment = 2..999，width = 998
```

### 元数据严格验证（normal 计算路径）

```text
trade_date: 严格 YYYY-MM-DD 且为真实日历日期（拒绝 2026-02-30 等）
session: 上游合法字符串（pre_open / call_auction / morning_session /
  midday_break / afternoon_session / close_pending / final / unavailable）
is_final: 严格 bool，必须与 session=="final" 一致
source_ids: 精确 list[str]，成员为非空字符串（拒绝子类），去重保序
fetched_at / snapshot_at: null 或可解析的 UTC ISO 8601
  若两者都有，fetched_at <= snapshot_at
```

时间戳前后空白一律拒绝（P2-1 修正）：

```text
先比较 value == value.strip()，不相等即非法
不得 strip 后放行，不得 strip 后规范化输出
以下全部固定 invalid：
  " 2026-07-31T15:10:00Z" / "2026-07-31T15:10:00Z "
  " 2026-07-31T15:10:00Z " / "\t2026-07-31T15:10:00Z"
  "2026-07-31T15:10:00Z\n"
```

以下行为保持：

```text
小写 z 可接受 / +00:00 可接受
非零 offset 拒绝 / naive timestamp 拒绝
fetched_at > snapshot_at 拒绝
```

元数据非法 -> `LADDER_CONTRACT_INVALID` + `GAP_OUTPUT_SUPPRESSED`，
metrics 全 null；不得修补非法元数据后继续输出正常 gap。

> 范围说明：元数据严格验证作用于 normal 计算路径；partial/unavailable
> 抑制路径不读取元数据（输出中性 null 值），以保证真实上游
> partial/unavailable envelope（其元数据可能为 null）仍按 §8 抑制映射
> 处理。

## 5. Exact Gap Definition

断层分析域固定为：

```text
[2, max_boards]
```

不包含 1 板与 0 板。

```text
occupied_boards = ladder 中出现的 boards（严格升序）
missing_boards = [2, max_boards] 中未出现在 occupied 的整数层级
```

示例：

```text
occupied = [2, 3, 4] -> missing = []
occupied = [2, 4]    -> missing = [3]
occupied = [4]       -> missing = [2, 3]
occupied = [2, 4, 6] -> missing = [3, 5]
```

## 6. Gap Segment Definition

相邻缺失层级合并为 segment：

```json
{"from_board": 3, "to_board": 5, "width": 3}
```

```text
width = to_board - from_board + 1
segments 按 from_board 升序
```

示例：

```text
missing = []          -> segments = []
missing = [3]         -> [{"from_board":3,"to_board":3,"width":1}]
missing = [2,3,5]     -> [{"from_board":2,"to_board":3,"width":2},
                          {"from_board":5,"to_board":5,"width":1}]
```

## 7. Output Schema

输出 envelope 精确包含 15 个字段：

```text
schema_version
trade_date
session
is_final
source_ids
fetched_at
snapshot_at
status
reason_codes
warnings
limitations
source_schema_version
source_status
source_reason_codes
metrics
```

metrics 精确包含 10 个字段：

```text
max_boards:            来自已验证上游梯队
sample_lianban_count:  上游 lianban_count
occupied_boards:       实际存在的 >=2 板层级
missing_boards:        2 到 max_boards 的缺失层级
gap_segments:          连续缺口区间
gap_level_count:       len(missing_boards)
gap_segment_count:     len(gap_segments)
largest_gap_width:     max(segment.width)，无 segment 时为 0
first_gap_board:       missing_boards[0]，无缺口时为 null
is_continuous:         missing_boards == []
```

不变量：

```text
gap_level_count == sum(segment.width)
gap_segment_count == len(gap_segments)
largest_gap_width <= gap_level_count
first_gap_board == null iff gap_level_count == 0
is_continuous == (gap_level_count == 0)
```

固定 limitations：

```text
derived from an already-computed ladder envelope
gap domain starts at board level 2
does not validate upstream consecutive-limit-up semantics
does not compute layered promotion rates
```

不透传调用方 limitations。

## 8. Status and Reason Codes

固定 reason-code 顺序：

```text
SOURCE_UNAVAILABLE
SOURCE_PARTIAL
UPSTREAM_LADDER_UNAVAILABLE
UPSTREAM_LADDER_PARTIAL
LADDER_CONTRACT_INVALID
GAP_OUTPUT_SUPPRESSED
```

映射：

```text
上游 normal   -> status=normal, reason_codes=[], metrics=具体值
上游 partial  -> status=partial,
                 reason_codes=[SOURCE_PARTIAL, UPSTREAM_LADDER_PARTIAL,
                               GAP_OUTPUT_SUPPRESSED],
                 metrics 全部 null（不得继续计算断层）
上游 unavailable -> status=unavailable,
                 reason_codes=[SOURCE_UNAVAILABLE,
                               UPSTREAM_LADDER_UNAVAILABLE,
                               GAP_OUTPUT_SUPPRESSED],
                 metrics 全部 null
合同/元数据/metrics 非法 -> status=invalid,
                 reason_codes=[LADDER_CONTRACT_INVALID,
                               GAP_OUTPUT_SUPPRESSED],
                 metrics 全部 null
```

`source_reason_codes`：

```text
只接受精确 list[str]（拒绝子类）
字符串必须非空
去重后保留首次出现顺序
未知上游码只能保留在 source_reason_codes，不得进入本模块 reason_codes
reason-code 合同非法 -> status=invalid, source_reason_codes=[]
```

## 9. Legal-zero / First-board Boundary

```text
max_boards=0, lianban_count=0, ladder=[]（合法零涨停）:
  occupied=[], missing=[], segments=[], gap_level_count=0,
  gap_segment_count=0, largest_gap_width=0, first_gap_board=null,
  is_continuous=true

max_boards=1, lianban_count=0, ladder=[]（只有首板）:
  输出同上（无连板梯队，无断层可分析）
```

断层不评价 1 板；1 板不是断层的一部分。

## 10. Examples

```text
max_boards=4, ladder=[{"boards":4,"count":1}]
  occupied=[4], missing=[2,3],
  segments=[{"from_board":2,"to_board":3,"width":2}],
  gap_level_count=2, first_gap_board=2, is_continuous=false

max_boards=7, occupied=[2,4,7]
  missing=[3,5,6],
  segments=[{"from_board":3,"to_board":3,"width":1},
            {"from_board":5,"to_board":6,"width":2}],
  gap_level_count=3, gap_segment_count=2, largest_gap_width=2,
  first_gap_board=3, is_continuous=false

max_boards=2, occupied=[2] -> missing=[], is_continuous=true
```

## 11. Exception Boundary

```text
公共函数只捕获 except Exception
普通异常（RuntimeError / ValueError / TypeError 等）-> 固定 invalid
  envelope（LADDER_CONTRACT_INVALID + GAP_OUTPUT_SUPPRESSED，
  metrics 全 null）
emergency fallback 不调用任何业务 helper、不再次读取输入对象、
  不包含异常文本、不泄漏异常类型/路径/URL/traceback
emergency fallback 直接构造完整固定字面量（limitations 与 null metrics
  均为新建字面量），不依赖模块级可变模板
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

失败输出不依赖模块级可变模板（P2-2 修正）：

```text
模块不定义 _METRICS_NULL / _LIMITATIONS 运行时对象
所有 envelope 的 limitations 每次通过新建字面量产生
suppressed / invalid / emergency 的 metrics 每次通过新建字面量产生
即使模块属性被外部注入伪造 _METRICS_NULL / _LIMITATIONS，
  normal / partial / unavailable / invalid / emergency 输出不受影响
修改第一次调用输出的 limitations / metrics 不影响第二次调用
```

## 12. Input Immutability

```text
调用前后输入深度相等（列表与 dict 内容不变）
不得 sort 输入 ladder、修改 source_ids、修改 reason_codes、
  向输入 metrics 写字段
输出列表与输入列表不共享可变引用
```

## 13. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_ladder_gap.py`）：

```text
安全上限 1000（max_boards/boards 边界）
超限 1001 / 超大整数 10**30（含 gap helper 未被调用的调用计数证明）
超长 ladder（长度 > 999）
时间戳前后空格 / tab / newline
模块全局污染（伪造 _METRICS_NULL / _LIMITATIONS）
emergency 全局污染 / 失败输出跨调用隔离
合法零涨停 / 只有首板 / 只有二板 / 连续 2-3-4 板
单缺口 / 起始缺口 / 末端前缺口 / 多个分离缺口 / 连续多层缺口
最高层很高但样本很少 / count 不影响 occupied level / count 守恒
未排序 / 重复 boards / boards/count bool / float/string
boards<2 / count<=0 / max_boards 不一致 / lianban_count 不一致
额外字段 / 缺失字段 / 子类伪装
source partial/unavailable 抑制
source reason-code 校验（去重保序、未知码保留、非法即 invalid）
元数据校验（真实日期、session、is_final、source_ids、UTC、先后关系）
调用方 gap 字段忽略 / limitations 不透传
输入不可变 / 输出无共享引用
普通异常固定 fallback（RuntimeError/ValueError/TypeError x 5 helper）
异常文本不泄漏
KeyboardInterrupt/SystemExit/GeneratorExit 传播
真实上游 compute_limit_up_ladder 输出联合路径
```

独立验证脚本（一次性，不提交）：

```text
全部基础案例 + 500 组随机合法 occupied-level 集合
（max_boards 2..30，随机 occupied 子集，随机正整数 count）
missing_boards 与数学集合差一致
segments 无损展开回 missing_boards
segments 互不重叠且不相邻
gap_level_count 守恒 / largest_gap_width 正确
partial/unavailable 不计算 / 非法合同全部 suppressed
输入不可变 / 普通异常 fail closed / 进程控制异常传播
```

修正后独立验证（一次性，不提交）：

```text
随机 1000 组（seed 固定并报告）
max_boards 2..10 全部包含 max_boards 的 occupied 子集穷举
有界路径：max_boards=10**30 / 1001 立即 invalid 且不进入 gap helper
时间戳空白全部 invalid
伪造 _METRICS_NULL / _LIMITATIONS 后输出不受影响
normal/partial/unavailable/invalid/emergency 输出隔离
```

## 14. Limitations

```text
1. 断层只指 2 板至 max_boards 之间缺失的整数板级
2. 不评价 1 板
3. 不计算晋级率（layered_promotion_rates 恒未实现）
4. 不验证上游 consecutive lbc 的来源语义
5. 不接入生产页面 / API / 调度器
6. 输出依赖上游已批准 ladder envelope 的正确性
7. 元数据严格验证仅作用于 normal 计算路径（抑制路径输出中性值）
```

## 15. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- 上游合同 / 元数据 / 状态 / reason codes 严格验证
- 断层与缺口区间定义机械可复算
- 普通异常固定 fallback，进程控制异常自然传播
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称 Slice 2 全部完成或页面/API 已完成
- 板级安全上限 1000 属于资源安全合同，不是市场历史结论
```
