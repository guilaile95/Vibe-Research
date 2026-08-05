# BK-11 snapshot selector v0.1

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

- 接收快照元数据行列表（与 Slice 3a `list_snapshots` 输出同构：
  {trade_date, session, schema_version, stored_at}）
- 为每个 trade_date 确定性选择每日权威快照
- 服务 Daily Review 历史区块与页面接入前的基础模块

### Non-goals（硬性）

```text
- 不读取存储 / 数据库 / live 外部数据（调用方传入内存列表）
- 不验证快照内容语义
- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不评估 legal zero（Blocker 6）
- 不接入 API / 页面 / 调度器
```

## 3. Input Contract

```text
type(rows) is list，非空
每行精确 4 字段 {trade_date, session, schema_version, stored_at}
trade_date: 严格 YYYY-MM-DD 真实日历日期
session: 8 会话词表
schema_version: 非空字符串
stored_at: 非空字符串
```

违反：

```text
非 list / 空列表        -> INPUT_CONTRACT_INVALID + OUTPUT_SUPPRESSED
任一行形状非法          -> ROW_CONTRACT_INVALID + OUTPUT_SUPPRESSED
```

## 4. Selection Rules

每个 trade_date 独立选择：

```text
1. final 硬优先（任何非 final 会话都不能胜过 final）
2. 无 final 时按会话时间序取最高
   pre_open < call_auction < morning_session < midday_break <
   afternoon_session < close_pending < final < unavailable
   （unavailable 为最高非 final 状态）
3. 同优先级同会话多版本：取 stored_at 最新（字符串比较）
4. 仍相同：取 schema_version 字典序较大者（全序决胜键）
5. 全部相等：取排序后的首条（确定性）
```

输入顺序不影响结果（模块内部按确定性全序
(trade_date, 优先级, session_rank, stored_at, schema_version) 排序）。

## 5. Output Schema

```text
schema_version
status
reason_codes
warnings
limitations
selection: [{trade_date, session, schema_version, stored_at}, ...]
```

selection 按 trade_date 升序。

固定 limitations：

```text
deterministic per-date snapshot selection
prefers final session, then session time order, then latest stored_at
does not read storage or live data
does not validate snapshot content semantics
no per-stock cross-day identity tracking
```

## 6. Status and Reason Codes

固定 reason-code 顺序：

```text
INPUT_CONTRACT_INVALID
ROW_CONTRACT_INVALID
OUTPUT_SUPPRESSED
```

全部合法 -> normal, reason_codes=[]。

## 7. Determinism

```text
相同输入（任意顺序）-> 完全相同的 selection
```

## 8. Exception Boundary

```text
公共入口只捕获 except Exception
普通异常 -> 固定 invalid envelope（INPUT_CONTRACT_INVALID +
  OUTPUT_SUPPRESSED，selection=[]）
emergency fallback 直接构造完整固定字面量，零业务 helper、
  零输入读取、零异常文本
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

## 9. Input Immutability

```text
调用前后输入深度相等
输出 selection 为新建列表，不共享输入引用
```

## 10. Examples

```text
rows:
  2026-07-31 afternoon_session（stored 10:00）
  2026-07-31 final（stored 09:00）
  2026-07-30 final（stored 08:00）
selection:
  [{2026-07-30, final, ...}, {2026-07-31, final, ...}]
  （07-31 取 final，即使其 stored_at 更早）
```

## 11. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_snapshot_selector.py`）：

```text
公开合同 / 单行 / final 优先 / 会话时间序 / 同会话最新 stored_at
多日期升序 / 输入乱序确定性 / 平局确定性
合同（非 list / 空 / 行形状 / 日期 / 会话 / schema / stored_at）
输入不可变 / 引用隔离 / 跨调用隔离
普通异常固定 fallback（3 helper x 3 异常类型）
进程控制异常传播
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 12. Limitations

```text
1. 只做元数据选择，不验证快照内容
2. stored_at 为字符串比较（ISO 格式保证可比）
3. 不读取存储；调用方负责提供行列表
4. 不接入生产页面 / API / 调度器
```

## 13. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- 选择规则机械可复算
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称页面/API 已完成
```
