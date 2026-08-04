# BK-11 涨停池结构化来源适配器 v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 5 | OPEN |
| Blocker 6 | PARTIALLY CLOSED — 适配器已区分 legal zero / 非交易日 / 传输 / 解析 / 限流 / 访问控制 / 上游空 / 结构异常 / malformed response / 日历依赖失败；正向 legal-zero 证据仍依赖未来可信 final 生产者 |
| Blocker 7 | CLOSED — ST/\*ST included、BSE excluded 的 universe 合同已落地；纯 universe 排除不制造 partial 也不产生 UNEXPLAINED_EMPTY |
| Blocker 8 | OPEN（本轮未关闭） |
| Blocker 9 | OPEN（本轮未关闭） |
| implementation_allowed(layered_promotion_rates) | false |

## 2. Scope and Non-goals

### Scope

- 独立、失败关闭的 `getTopicZTPool` 来源适配器
- 保留 transport / HTTP / parse / schema / empty / universe 等结构化状态
- 标准化 `stock_code + lbc` 最小行集
- 十字段合同 + 扩展字段输出
- ST/\*ST included、BSE excluded universe 合同
- 三类空结果区分（source empty / target universe empty / invalid empty）

### Non-goals

- layered_promotion_rates 计算
- 跨日 numerator / denominator
- final 快照生产者
- 稳定窗口
- Data Health 全局注册
- API / 前端 / 数据库 / 调度器 / 历史回填 / 缓存服务
- Blocker 2/3 的新 live 探针
- 修改既有 `astock.em_zt_topic_pool`

## 3. Existing Failure Mode

既有 `astock.em_zt_topic_pool` 对所有异常统一捕获并返回 `[]`，无法区分：

- 传输超时 / 连接断开
- HTTP 429 限流 / 401/403 访问控制
- JSON 解析失败
- 上游 `data` 或 `pool` 为 `null`
- 非交易日
- 空池（legal zero vs unexplained empty vs target universe empty）
- malformed HTTP response（status_code 非 int / 缺失 / 越界）
- 交易日历依赖异常

本适配器通过结构化状态区分上述场景。

## 4. Adapter Public API

```python
SCHEMA_VERSION = "short-term-limit-up-pool-adapter-v0.1"

def fetch_limit_up_pool_snapshot(requested_trade_date: str) -> dict:
    ...
```

`__all__` 仅包含 `["SCHEMA_VERSION", "fetch_limit_up_pool_snapshot"]`。

不得给公开函数增加 `caller_final / is_final / legal_zero / session / trusted / request_fn` 等由调用方任意声明可信状态的参数。

## 5. Output Schema

每次调用返回完整 dict，至少包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| schema_version | str | 固定 `"short-term-limit-up-pool-adapter-v0.1"` |
| source_id | str | 固定 `"eastmoney_getTopicZTPool"` |
| endpoint | str | 固定 `"getTopicZTPool"` |
| requested_trade_date | str | 请求日期 |
| observed_at | str | UTC ISO 时间戳 |
| status | str | `"normal"` / `"partial"` / `"unavailable"` |
| reason_codes | list[str] | 结构化原因码（固定顺序，仅允许已知集合） |
| rows | list[dict] | `[{stock_code, lbc}]` |
| transport_success | bool | 传输层是否成功 |
| parse_success | bool | JSON 解码成功且顶层为 dict |
| required_field_present | bool | `data` 和 `pool` 字段均存在 |
| data_array_present | bool | `pool` 实际为 list |
| trade_date_match | true/false/null | payload 日期是否匹配 |
| row_count | int | `len(rows)` |
| legal_zero | bool | 本版本始终 `False` |
| upstream_null | bool | `data` 或 `pool` 为 `null` |
| unexplained_empty | bool | 原始 pool 为空 |
| coverage_warning | bool | 存在覆盖度问题 |
| source_pool_row_count | int | 上游 data.pool 原始元素数量 |
| target_universe_empty_after_filter | bool | pool 非空但目标 universe 过滤后为空 |
| http_status | int/None | HTTP 状态码（安全提取） |
| error_class | str | normal→NONE；partial/unavailable→reason_codes[0] |
| excluded_universe_count | int | 因 universe 排除的行数 |
| invalid_row_count | int | 无效行数 |
| duplicate_code_count | int | 目标 universe 内重复代码数 |

不得输出：股票名称、价格、成交额、行业、封单字段、完整响应、异常原文、访问凭据。

## 6. Ten-field Contract

以下十字段必须始终存在且类型正确：

| 字段 | 类型 |
|------|------|
| transport_success | bool |
| parse_success | bool |
| required_field_present | bool |
| data_array_present | bool |
| trade_date_match | true \| false \| null |
| row_count | non-negative int |
| legal_zero | bool |
| upstream_null | bool |
| unexplained_empty | bool |
| coverage_warning | bool |

扩展字段 `source_pool_row_count` 和 `target_universe_empty_after_filter` 同样在所有返回路径中存在。

## 7. Trading-date Validation

不得发起网络请求的场景：

- 非字符串 / 空字符串 / 非严格 `YYYY-MM-DD`
- 不存在日期 / 超出 trade_calendar 支持范围
- 未来日期 / 周末 / 官方休市日

判断规则：`requested_trade_date` 必须严格存在于已验证 sessions 中且 `<= Asia/Shanghai today`。

不满足时：`status = unavailable`，`reason_codes = ["NON_TRADING_DATE"]`。

### 交易日历依赖失败关闭

对 `trade_calendar._load_calendar()` 和 `_today_shanghai()` 的调用包裹在 `Exception` 边界内：

- 普通异常 → `TRADING_CALENDAR_UNAVAILABLE`，不发起网络请求
- `_load_calendar` 返回 None / 非容器类型（仅允许 tuple/list/set/frozenset）/ 空容器 → `TRADING_CALENDAR_UNAVAILABLE`
- sessions 每个成员必须为严格合法 `YYYY-MM-DD` 字符串（`type(member) is str` 且真实日历日期）；任一成员不可信 → 整体 `TRADING_CALENDAR_UNAVAILABLE`，不得忽略坏成员，也不得将不可信日历误报为 `NON_TRADING_DATE`
- `_today_shanghai` 返回 None / 非精确 `datetime.date`（`type(today) is date`）→ `TRADING_CALENDAR_UNAVAILABLE`；`datetime` 是 `date` 的子类但含时间分量，naive/aware 均不接受，避免后续比较抛 TypeError
- KeyboardInterrupt / SystemExit / GeneratorExit 自然传播

内部只读调用，不修改交易日历模块。

## 8. Transport and HTTP Classification

### 传输异常

| 异常类型 | reason_code | transport_success |
|----------|-------------|-------------------|
| `requests.Timeout`（含 Connect/Read） | REQUEST_TIMEOUT | false |
| `requests.ConnectionError`（含 proxy/TLS） | TRANSPORT_ERROR | false |

仅捕获 `Exception`，`KeyboardInterrupt` / `SystemExit` / `GeneratorExit` 自然传播。

不得在结果中保存异常字符串。

### HTTP 状态码安全提取

通过 `_safe_http_status(response)` 安全提取状态码：

- 仅接受 int（bool 不允许）
- 有效范围 100–599
- 缺失 / 属性访问异常 / 非 int / 越界 → None

`response = None` / `status_code` 缺失 / 非 int / 越界 / 属性抛异常时：

```text
status = unavailable
reason_codes = ["HTTP_ERROR"]
http_status = null
transport_success = true
parse_success = false
```

### HTTP 分类

| 状态码 | reason_code | transport_success | parse_success |
|--------|-------------|-------------------|---------------|
| 429 | RATE_LIMITED | true | false |
| 401/403 | ACCESS_RESTRICTED | true | false |
| 其他非 2xx | HTTP_ERROR | true | false |

## 9. JSON and Schema Classification

HTTP 2xx 后通过 `_safe_call_json(response)` 安全检查：

- `response.json` 属性存在且可调用
- 调用时普通 `Exception` 失败关闭
- json 缺失 / None / 非 callable / 属性抛异常 / ValueError / TypeError → PARSE_ERROR

### Schema 字段语义

```text
parse_success:           JSON 解码成功且顶层为 dict
required_field_present:  data 和 data.pool 两个字段均存在
data_array_present:      data.pool 实际为 list
```

| 条件 | parse_success | required_field_present | data_array_present | reason_code |
|------|---------------|------------------------|--------------------|----|
| json() 异常 | false | false | false | PARSE_ERROR |
| 顶层非 dict | false | false | false | DATA_ARRAY_INVALID |
| data 缺失 | true | false | false | REQUIRED_FIELD_MISSING |
| data = null | true | false | false | UPSTREAM_NULL |
| data 非 dict | true | false | false | DATA_ARRAY_INVALID |
| pool 缺失 | true | false | false | REQUIRED_FIELD_MISSING |
| pool = null | true | false | false | UPSTREAM_NULL |
| pool 非 list | true | true | false | DATA_ARRAY_INVALID |
| pool = list | true | true | true | — |

只有 `pool` 为 list 才进入行标准化。

## 10. Date-binding Semantics

候选字段：`payload.trade_date` / `payload.date` / `payload.qdate` / `data.trade_date` / `data.date` / `data.qdate`。

日期格式：`YYYY-MM-DD` / `YYYYMMDD`。必须使用真实日历日期解析（`date(year, month, day)`），非仅正则匹配。

### 决策规则

1. 收集所有存在且非 null 的候选值
2. 对每个值严格解析为日历日期；非法日期（如 `2026-02-30` / `20260230`）标记为 invalid
3. 若存在至少一个合法候选与 requested date 不同 → **mismatch** / unavailable / TRADE_DATE_MISMATCH
4. 合法 mismatch 优先于非法候选：存在合法 mismatch 时，即使同时存在非法候选也按 mismatch 失败关闭
5. 不存在合法 mismatch，但存在任意非法候选 → **null** / partial + DATE_BINDING_UNVERIFIED（匹配 + 非法不得返回 true）
6. 全部存在的候选均合法且全部匹配 → **true**
7. 无候选 → **null** / partial + DATE_BINDING_UNVERIFIED

即使另一个字段匹配，只要存在合法 mismatch 也必须失败关闭。

非法日期字段不得产生 mismatch（因无法证明日期不一致）。
非法日期字段也不得被忽略：存在合法匹配 + 非法候选时，日期绑定无法验证，必须保持 null / partial。

由于 Blocker 3 尚未关闭，`trade_date_match = null` 时不得伪造为 `true`。不得在本轮升级历史日期绑定证据。

## 11. Universe Contract

唯一纳入代码前缀：`60xxxx / 00xxxx / 30xxxx / 68xxxx`。

明确排除：`4xxxxx / 8xxxxx / 920xxx / 9xxxxx / 200xxx / 900xxx`、ETF、LOF、可转债、基金、指数。

实现：先确认严格六位数字字符串，再 `stock_code.startswith(("60", "00", "30", "68"))`。

ST included、\*ST included。不得根据名称包含 ST/\*ST 排除记录。

被 universe 正常排除的合法行：不计 `invalid_row_count`，不计 `duplicate_code_count`，不导致 `partial`，计入 `excluded_universe_count`。重复的 excluded 行仍按来源行分别计入。

纯 universe 排除（无 invalid、无 duplicate、`excluded_universe_count == source_pool_row_count`）时：

- 日期已验证：`status = normal`，`reason_codes = []`，`coverage_warning = false`
- 日期未验证：`status = partial`，`reason_codes = ["DATE_BINDING_UNVERIFIED"]`
- `target_universe_empty_after_filter = true`
- `unexplained_empty = false`

## 12. Row Normalization

来源字段：

- `stock_code`：优先读取 `c`，允许兼容 `code`
- `lbc`：读取 `lbc`

`stock_code`：必须为六位数字字符串，不得从 int 自动补零，不得整数化。

`lbc`：必须为 int，bool 不允许，必须 > 0，不得从缺失值默认成 1。

无效行：不进入 `rows`，不占用 seen，`invalid_row_count += 1`，`status` 至少 `partial`，`reason_codes` 包含 `INVALID_POOL_ROW`，`coverage_warning = true`。

重复代码（`duplicate_code_count`）：只统计通过格式、lbc 和 universe 校验后的目标 universe 重复。保留首次合法且属于 universe 的记录。`duplicate_code_count += 1`，`reason_codes` 包含 `DUPLICATE_STOCK_CODE`。

最终 `rows`：按 `stock_code` 严格升序，`stock_code` 唯一。

## 13. Empty and Legal-zero Semantics

适配器区分三类空结果：

### Source empty（原始 pool 为空）

```text
source_pool_row_count = 0
rows = []
legal_zero = false
unexplained_empty = true
target_universe_empty_after_filter = false
status = partial
reason_codes = ["UNEXPLAINED_EMPTY"]
coverage_warning = true
```

### Target universe empty after filter（pool 非空，全部因 universe 排除）

```text
source_pool_row_count > 0
rows = []
excluded_universe_count == source_pool_row_count
invalid_row_count = 0
duplicate_code_count = 0
target_universe_empty_after_filter = true
unexplained_empty = false
status = normal（日期已验证）或 partial（日期未验证）
```

### Invalid/coverage empty（pool 非空，行全部无效或 mixed）

```text
source_pool_row_count > 0
rows = []
invalid_row_count > 0（或 mixed invalid + excluded）
unexplained_empty = false
target_universe_empty_after_filter = false
status = partial
reason_codes 按固定顺序包含适用码
```

空原因已由计数解释时，不得附加 `UNEXPLAINED_EMPTY`。

### Legal zero

即使 HTTP 200 + JSON 正常 + `data.pool` 存在，也不得仅凭空数组设置 `legal_zero = true`。

本版 `legal_zero` 始终 `False`：本仓库尚无可信 final 快照生产者可独立证明"当日全市场确实无涨停"。

适配器已阻止空数组误判为合法零值，但 legal-zero 的正向确认仍依赖未来可信 final 生产者或明确来源证据。

因此 Blocker 6 是否完全关闭，需要结合 Blocker 5 的后续实现重新评估。

不得添加调用方布尔参数绕过该限制。

## 14. Status and Reason-code Matrix

| status | 条件 |
|--------|------|
| normal | 完全有效、非空、日期匹配；或纯 universe 排除且日期已验证 |
| partial | 有效但日期未验证 / 存在 invalid 或 duplicate / 空池 |
| unavailable | 输入无效 / 非交易日 / 日历不可用 / 传输失败 / malformed response / HTTP 错误 / 解析失败 / 结构异常 / 日期不匹配 |

### Status 不变量

```text
normal      → coverage_warning = false
partial     → coverage_warning = true
unavailable → coverage_warning = false, rows = []
row_count   == len(rows)
legal_zero  始终 false
```

允许 `normal + rows=[] + target_universe_empty_after_filter=true`（来源池非空、目标 universe 内无记录）。

### error_class 统一

```text
normal      → error_class = "NONE"
partial     → error_class = reason_codes[0]
unavailable → error_class = reason_codes[0]
```

### reason code 固定集合

`reason_codes` 输出只能来自以下 16 个已知码，未知 code 不得进入输出：

```text
NON_TRADING_DATE, TRADING_CALENDAR_UNAVAILABLE, REQUEST_TIMEOUT, TRANSPORT_ERROR,
RATE_LIMITED, ACCESS_RESTRICTED, HTTP_ERROR, PARSE_ERROR, UPSTREAM_NULL,
REQUIRED_FIELD_MISSING, DATA_ARRAY_INVALID, TRADE_DATE_MISMATCH,
DATE_BINDING_UNVERIFIED, INVALID_POOL_ROW, DUPLICATE_STOCK_CODE, UNEXPLAINED_EMPTY
```

固定顺序由 `_REASON_CODE_ORDER` 定义。

## 15. Mapping to Layered Promotion Contract

本适配器为未来 layered promotion rates 计算提供标准化输入：

- `rows` 中的 `{stock_code, lbc}` 可直接用于跨日 numerator/denominator 计算
- `status` / `reason_codes` / `coverage_warning` 可用于上游数据质量门控
- `excluded_universe_count` / `invalid_row_count` / `duplicate_code_count` 提供数据清洗审计
- `source_pool_row_count` / `target_universe_empty_after_filter` 区分空结果来源

但 `implementation_allowed(layered_promotion_rates) = false`，本轮不实现计算逻辑。

## 16. Blocker 6 Decision

**PARTIALLY CLOSED**

适配器已区分以下状态：

- legal zero（本版本始终 false，因无可信 final 生产者）
- 非交易日（NON_TRADING_DATE）
- 交易日历不可用（TRADING_CALENDAR_UNAVAILABLE，含依赖异常/类型错误）
- 传输超时（REQUEST_TIMEOUT）
- 传输错误（TRANSPORT_ERROR）
- 限流（RATE_LIMITED）
- 访问控制（ACCESS_RESTRICTED）
- HTTP 错误（HTTP_ERROR，含 malformed status_code）
- JSON 解析失败（PARSE_ERROR，含 json 不可调用）
- 上游 null（UPSTREAM_NULL）
- 结构异常（REQUIRED_FIELD_MISSING / DATA_ARRAY_INVALID）
- 日期不匹配（TRADE_DATE_MISMATCH，严格收集全部候选）
- 日期绑定未验证（DATE_BINDING_UNVERIFIED）
- 无效行（INVALID_POOL_ROW）
- 重复代码（DUPLICATE_STOCK_CODE）
- 未解释空（UNEXPLAINED_EMPTY）
- 进程控制异常（KeyboardInterrupt / SystemExit / GeneratorExit 自然传播，不伪装）

剩余：正向 legal-zero 证据依赖未来可信 final 快照生产者或明确来源证据。Blocker 6 完全关闭需要结合 Blocker 5 的后续实现重新评估。

## 17. Blocker 7 Decision

**CLOSED**

universe 合同满足全部关闭条件：

- ST included（不根据名称排除）
- \*ST included（不根据名称排除）
- BSE excluded（`4xxxxx / 8xxxxx / 920xxx` 等前缀）
- 目标前缀正确（`60 / 00 / 30 / 68`）
- `excluded_universe_count` 正确（每条合法排除行计数，含重复 excluded）
- `duplicate_code_count` 仅统计目标 universe 内重复（excluded 重复不计入）
- 纯 universe 排除不制造 partial（日期已验证时为 normal）
- 纯 universe 排除不产生 UNEXPLAINED_EMPTY
- 测试真实断言 status / reason_codes / flags
- 156 项聚焦测试全部通过

## 18. Remaining Blockers

| Blocker | 状态 | 说明 |
|---------|------|------|
| 2 | OPEN | post_holiday pair empty, cause not_verified |
| 3 | OPEN | requested_date_binding + final_snapshot partially_verified |
| 4 | CLOSED_BY_NON_ADOPTION | getYesterdayZTPool 不采用 |
| 5 | OPEN | legal_zero 正向证据 |
| 6 | PARTIALLY CLOSED | 见 §16 |
| 7 | CLOSED | 见 §17 |
| 8 | OPEN | 本轮未关闭 |
| 9 | OPEN | 本轮未关闭 |

`implementation_allowed(layered_promotion_rates) = false`。

## 19. Licensing and Data-retention Boundary

本文件不作版权、原创性或再分发许可的法律结论。

数据保留边界：

- 仅提交 `stock_code` 和 `lbc` 到 rows
- 不提交完整原始 payload、股票名称或请求凭据
- 不提交异常原文或完整 URL
- 不提交访问凭据值

## 20. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- 适配器实现了完整的失败关闭状态区分（Blocker 6 部分关闭）
- universe 合同完整落地（Blocker 7 关闭），含三类空结果正确区分
- 156 项聚焦测试全部通过，2297 项 backend 离线测试全部通过
- 无新增运行时依赖，不修改既有模块
- 进程控制异常（KeyboardInterrupt / SystemExit / GeneratorExit）自然传播
- malformed HTTP response 安全结构化返回
- 交易日历依赖失败关闭

剩余阻断：

- Blocker 5（legal_zero 正向证据）仍 OPEN
- Blocker 6 完全关闭依赖 Blocker 5
- Blocker 8/9 本轮未关闭
- `layered_promotion_rates` 实现仍不允许
