# BK-11 T+1 可信 final 涨停池快照生产者 v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 5 | CLOSED for T+1 completed-session snapshots |
| Blocker 6 | PARTIALLY CLOSED — 本生产者不得正向证明 legal zero |
| Blocker 7 | CLOSED（沿用适配器 universe 合同） |
| implementation_allowed(layered_promotion_rates) | false |

## 2. Scope and Non-goals

### Scope

- 独立、失败关闭的 T+1 可信 final 快照生产者
- 内部复用已批准的 `short_term_limit_up_pool_adapter`，不绕过适配器
- 三次连续观测 + 2.2 秒间隔 + 4.4 秒稳定窗口 + 内容完全一致 → final
- 严格交易日期绑定与字段完整性校验
- 固定 reason-code 集合、finality 不变量、进程控制异常自然传播

### Non-goals

- 同日盘中 final / 同日收盘即时 final（不通过任意时钟阈值猜测同日来源已 final）
- legal-zero 正向确认
- Blocker 2 / 3 的 live 探针
- 历史端点上游语义验证、跨日 lbc 语义验证
- layered_promotion_rates 计算
- API / 前端 / 数据库 / 调度器 / 历史回填 / 缓存服务
- Data Health 全局注册
- 新增运行时依赖

## 3. Reused Components

```python
import trade_calendar
import short_term_limit_up_pool_adapter as pool_adapter
```

- 运行时观测只通过 `pool_adapter.fetch_limit_up_pool_snapshot(requested_trade_date)`
- 交易日历只通过 `trade_calendar._load_calendar()` / `_today_shanghai()`
- 稳定窗口使用标准库 `time.sleep` / `time.monotonic`
- 不得直接调用 `astock.em_get` / `astock.em_zt_topic_pool`，不得新建
  requests Session，不得复制适配器实现

## 4. Public API

```python
SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"
REQUIRED_OBSERVATIONS = 3
OBSERVATION_INTERVAL_SECONDS = 2.2

def fetch_final_limit_up_pool_snapshot(requested_trade_date: str) -> dict:
    ...
```

`__all__` 仅包含以上四个公开符号。公开函数不得接受
`is_final / session / trusted / legal_zero / observations / fetch_fn / clock /
sleep_fn / caller_override` 等由调用方提供可信状态或观测结果的参数。

测试可 monkeypatch 模块私有引用（`_fetch_adapter_snapshot` / `_sleep` /
`_monotonic`），但公开 API 不得接受注入参数。

## 5. T+1 Completed-session Boundary

本版本只支持：

```text
requested_trade_date < Asia/Shanghai today
```

即已完成的历史交易日。不支持当日盘中、当日收盘待确认、当日 15:00 后即时
final、未来日期、非交易日。

日期预检必须在首次适配器请求前完成。分类：

```text
输入格式或非 session:       NON_TRADING_DATE / unavailable
requested_trade_date >= today: NOT_FINAL / unavailable
交易日历不可用:             TRADING_CALENDAR_UNAVAILABLE / unavailable
```

不得把今日或未来日期标记为 final。

## 6. Trading-calendar Trust Boundary

复用已批准的严格规则：

- sessions 容器仅允许 tuple / list / set / frozenset
- 容器必须非空
- 每个成员 `type(item) is str` 且为严格合法 `YYYY-MM-DD` 日历日期
- 任一成员不可信 → 整体 `TRADING_CALENDAR_UNAVAILABLE`，不得忽略坏成员
- today 必须 `type(today) is datetime.date`；datetime / date 子类 / 字符串 /
  None / object 均拒绝
- 普通 `Exception` → `TRADING_CALENDAR_UNAVAILABLE`，0 网络请求
- KeyboardInterrupt / SystemExit / GeneratorExit 自然传播

## 7. Observation Sequence

满足日期预检后，依次调用适配器三次：

```text
observation 1
sleep 2.2
observation 2
sleep 2.2
observation 3
```

- required observations: 3
- sleep intervals: 2
- configured interval: 2.2 秒
- configured total stability window: 4.4 秒
- 第三次后不再 sleep
- 每次观测开始时间使用 monotonic 时钟记录

来源失败 / partial / schema 无效时失败即停，不继续无意义请求与等待。

## 8. Stability-window Contract

最终确认要求：

```text
第三次开始时间 - 第一次开始时间 >= 4.4 seconds
```

允许极小浮点容差（`actual_window + 1e-9 >= required_window`）。

不得依赖 wall clock 秒级字符串、`observed_at` 字符串差值或调用方声称已等待。

monotonic 时钟抛普通异常 / 返回 bool / 非数字 / NaN / inf / 倒退 /
稳定窗口不足，以及 `_sleep` 抛普通异常 → 全部失败关闭为
`STABILITY_WINDOW_ERROR` / unavailable。进程控制异常自然传播。

## 9. Adapter Admission Contract

每次观测必须为完整 dict 且满足：

```text
schema_version == short-term-limit-up-pool-adapter-v0.1
requested_trade_date == 请求日期
status == normal
reason_codes == []
transport_success == true
parse_success == true
required_field_present == true
data_array_present == true
trade_date_match == true
coverage_warning == false
upstream_null == false
unexplained_empty == false
legal_zero == false
row_count == len(rows)
source_pool_row_count >= row_count
invalid_row_count == 0
duplicate_code_count == 0
```

允许两类正常快照：

1. 正常非空目标池：`rows` 非空，`target_universe_empty_after_filter = false`
2. 来源池非空但目标 universe 为空：`rows = []`、
   `source_pool_row_count > 0`、`excluded_universe_count == source_pool_row_count`、
   `target_universe_empty_after_filter = true`、`legal_zero = false`

不得接受：原始 source pool 为空、UNEXPLAINED_EMPTY、partial、unavailable、
`trade_date_match` null/false、coverage_warning=true、invalid/duplicate 行、
不完整 schema、调用方构造的 `legal_zero=true`。

## 10. Row and Schema Validation

每个 row 只能包含：

```json
{"stock_code": "000001", "lbc": 1}
```

要求：row 为 dict；字段集合严格等于 `stock_code + lbc`（不得忽略额外字段）；
stock_code 为严格六位数字字符串；lbc 为 int > 0（bool 不允许）；rows 按
stock_code 严格升序且唯一。

任何行合同错误 → `SNAPSHOT_SCHEMA_INVALID` / unavailable /
`is_final = false` / `snapshot = null`。

## 11. Canonical Stability Fingerprint

三次观测必须对以下确定性内容完全一致：

```text
requested_trade_date
rows
row_count
source_pool_row_count
excluded_universe_count
invalid_row_count
duplicate_code_count
target_universe_empty_after_filter
trade_date_match
legal_zero
```

排除：observed_at、http_status、网络请求耗时、对象内存地址、字段插入顺序。

指纹使用 canonical JSON（`ensure_ascii=False, sort_keys=True,
separators=(",", ":")`）+ SHA-256；最终输出不依赖 hash 碰撞做唯一判断，
同一观测通过同一 canonical 序列化保证。

三次指纹或结构不一致 →

```text
status = unavailable
is_final = false
session = not_final
reason_codes = [NOT_FINAL, SNAPSHOT_UNSTABLE]
snapshot = null
```

不得选择其中一份结果继续标 final。

## 12. Source Partial and Failure Semantics

任一观测 `status = unavailable` →

```text
status = unavailable
is_final = false
session = not_final
reason_codes 至少包含 SOURCE_UNAVAILABLE
snapshot = null
```

任一观测 `status = partial` →

```text
status = partial
is_final = false
session = not_final
reason_codes 至少包含 SOURCE_PARTIAL
snapshot = null
```

适配器普通异常 → `SOURCE_UNAVAILABLE`；异常原文不得进入输出。适配器 reason
code 保留时映射到生产者固定 reason-code 集合，未知字符串不进入输出。

## 13. Output Schema

所有普通返回路径包含：

| 字段 | 类型 |
|------|------|
| schema_version | str |
| requested_trade_date | str |
| observed_at | UTC ISO string |
| status | normal / partial / unavailable |
| reason_codes | list[str] |
| session | final / not_final |
| is_final | bool |
| finality_basis | str / null |
| required_observations | int |
| completed_observations | non-negative int |
| stable_observation_count | non-negative int |
| observation_interval_seconds | float |
| required_stability_window_seconds | float |
| actual_stability_window_seconds | float / null |
| first_observation_monotonic | float / null |
| last_observation_monotonic | float / null |
| snapshot | dict / null |
| warnings | list[str] |

成功时：

```text
status = normal
reason_codes = []
session = final
is_final = true
finality_basis = three_identical_normal_observations
required_observations = 3
completed_observations = 3
stable_observation_count = 3
snapshot = 第三次完整适配器合同
warnings = []
```

失败时：`session = not_final`、`is_final = false`、`snapshot = null`。

## 14. Reason Codes and Status Matrix

固定集合与顺序：

```text
NON_TRADING_DATE
TRADING_CALENDAR_UNAVAILABLE
NOT_FINAL
SOURCE_UNAVAILABLE
SOURCE_PARTIAL
SNAPSHOT_SCHEMA_INVALID
SNAPSHOT_UNSTABLE
STABILITY_WINDOW_ERROR
```

未知 reason code 不得输出；去重并保持固定顺序。

| reason_code | status |
|-------------|--------|
| NON_TRADING_DATE | unavailable |
| TRADING_CALENDAR_UNAVAILABLE | unavailable |
| NOT_FINAL | unavailable |
| SOURCE_UNAVAILABLE | unavailable |
| SOURCE_PARTIAL | partial |
| SNAPSHOT_SCHEMA_INVALID | unavailable |
| SNAPSHOT_UNSTABLE | unavailable |
| STABILITY_WINDOW_ERROR | unavailable |

`partial` 只用于适配器明确返回 partial 的来源覆盖不完整场景。

## 15. Legal-zero Boundary

本生产者不得正向证明 legal zero。稳定重复的 `source pool = []` 仍不能证明
合法零涨停（适配器会将其标为 partial / UNEXPLAINED_EMPTY）。

`target_universe_empty_after_filter = true` 只表示目标 universe 没有记录，
不等于全市场 legal zero。

```text
legal_zero 正向确认: 未实现
Blocker 6: 继续 PARTIALLY CLOSED
```

## 16. Blocker 5 Decision

**CLOSED for T+1 completed-session snapshots**

关闭范围：

- 已完成历史交易日（`requested_trade_date < Asia/Shanghai today`）
- 适配器三次 normal 观测
- 严格交易日期绑定
- 字段完整性（admission + row/schema 校验）
- 连续 4.4 秒稳定窗口（monotonic）
- 内容完全一致（canonical 指纹）
- 失败关闭（含时钟、sleep、来源、schema、不稳定）

明确不包含：

- 同日盘中 final / 同日收盘即时 final
- legal-zero 正向确认
- 历史端点上游语义验证
- 跨日 lbc 语义验证

生产者逻辑与具体日期无关：任意两个已完成历史交易日（位于已验证 sessions
且严格早于 today）均可走同一流程生成 final 快照。不得扩大为同日实时生产者。

## 17. Remaining Blockers

| Blocker | 状态 | 说明 |
|---------|------|------|
| 1 | CLOSED | 沿用适配器结论 |
| 2 | OPEN | 本轮未推进 live 探针 |
| 3 | OPEN | 本轮未推进 requested_date_binding / final_snapshot 升级 |
| 4 | CLOSED_BY_NON_ADOPTION | getYesterdayZTPool 不采用 |
| 5 | CLOSED for T+1 completed-session snapshots | 见 §16 |
| 6 | PARTIALLY CLOSED | legal-zero 正向确认未实现 |
| 7 | CLOSED | 沿用适配器 universe 合同 |
| 8 | OPEN | 本轮未推进 partial-rates gate |
| 9 | OPEN | 本轮未推进 fixture verifier |

`implementation_allowed(layered_promotion_rates) = false`。

## 18. Licensing and Data-retention Boundary

本文件不作版权、原创性或再分发许可的法律结论。

不得保存或提交：完整 HTTP 响应、原始 payload、股票名称、价格、成交额、
Cookie、Token、Authorization、异常原文。最终快照只保留适配器已标准化的
最小合同（`stock_code + lbc` 及结构字段）。

不得增加请求并发；单次公开调用最多 3 次串行适配器调用。

## 19. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- T+1 final 生产者完整落地（Blocker 5 按 §16 范围关闭）
- 三次观测 + 4.4 秒稳定窗口 + canonical 指纹一致 → final
- 全部失败路径失败关闭，进程控制异常自然传播
- 126 项聚焦测试、282 项适配器联合测试、2423 项 backend 离线测试全部通过
- 无新增运行时依赖，不修改既有模块

剩余阻断：

- Blocker 6 完全关闭依赖 legal-zero 正向确认（未实现）
- Blocker 8 / 9 未关闭
- `layered_promotion_rates` 实现仍不允许
