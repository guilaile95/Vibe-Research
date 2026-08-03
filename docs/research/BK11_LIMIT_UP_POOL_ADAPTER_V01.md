# BK-11 涨停池结构化来源适配器 v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 5 | OPEN |
| Blocker 6 | PARTIALLY CLOSED — 适配器已区分 legal zero / 非交易日 / 传输 / 解析 / 限流 / 访问控制 / 上游空 / 结构异常；正向 legal-zero 证据仍依赖未来可信 final 生产者 |
| Blocker 7 | CLOSED — ST/\*ST included、BSE excluded 的 universe 合同已落地 |
| Blocker 8 | OPEN（本轮未关闭） |
| Blocker 9 | OPEN（本轮未关闭） |
| implementation_allowed(layered_promotion_rates) | false |

## 2. Scope and Non-goals

### Scope

- 独立、失败关闭的 `getTopicZTPool` 来源适配器
- 保留 transport / HTTP / parse / schema / empty / universe 等结构化状态
- 标准化 `stock_code + lbc` 最小行集
- 十字段合同输出
- ST/\*ST included、BSE excluded universe 合同

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
- 空池（legal zero vs unexplained empty）

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
| reason_codes | list[str] | 结构化原因码（固定顺序） |
| rows | list[dict] | `[{stock_code, lbc}]` |
| transport_success | bool | 传输层是否成功 |
| parse_success | bool | JSON 解析是否成功 |
| required_field_present | bool | `data` 和 `pool` 字段是否存在 |
| data_array_present | bool | `pool` 是否为 list |
| trade_date_match | true/false/null | payload 日期是否匹配 |
| row_count | int | `len(rows)` |
| legal_zero | bool | 本版本始终 `False` |
| upstream_null | bool | `data` 或 `pool` 是否为 `null` |
| unexplained_empty | bool | 空池且无法证明合法零值 |
| coverage_warning | bool | 存在覆盖度问题 |
| http_status | int/None | HTTP 状态码 |
| error_class | str | 错误分类标识 |
| excluded_universe_count | int | 因 universe 排除的行数 |
| invalid_row_count | int | 无效行数 |
| duplicate_code_count | int | 重复代码数 |

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

## 7. Trading-date Validation

不得发起网络请求的场景：

- 非字符串 / 空字符串 / 非严格 `YYYY-MM-DD`
- 不存在日期 / 超出 trade_calendar 支持范围
- 未来日期 / 周末 / 官方休市日

判断规则：`requested_trade_date` 必须严格存在于已验证 sessions 中且 `<= Asia/Shanghai today`。

不满足时：

```text
status = unavailable
reason_codes = ["NON_TRADING_DATE"]
transport_success = false
```

交易日历不可用时：

```text
status = unavailable
reason_codes = ["TRADING_CALENDAR_UNAVAILABLE"]
```

内部只读调用 `trade_calendar._load_calendar()` / `_today_shanghai()`，不修改交易日历模块。

## 8. Transport and HTTP Classification

### 传输异常

| 异常类型 | reason_code | transport_success |
|----------|-------------|-------------------|
| `requests.Timeout`（含 Connect/Read） | REQUEST_TIMEOUT | false |
| `requests.ConnectionError`（含 proxy/TLS） | TRANSPORT_ERROR | false |

不得在结果中保存异常字符串。

### HTTP

| 状态码 | reason_code | transport_success | parse_success |
|--------|-------------|-------------------|---------------|
| 429 | RATE_LIMITED | true | false |
| 401/403 | ACCESS_RESTRICTED | true | false |
| 其他非 2xx | HTTP_ERROR | true | false |

## 9. JSON and Schema Classification

HTTP 2xx 后：

| 条件 | reason_code |
|------|-------------|
| `response.json()` 抛异常 | PARSE_ERROR |
| 顶层非 dict | DATA_ARRAY_INVALID |
| `data` 缺失 | REQUIRED_FIELD_MISSING |
| `data` = null | UPSTREAM_NULL |
| `data` 非 dict | DATA_ARRAY_INVALID |
| `pool` 缺失 | REQUIRED_FIELD_MISSING |
| `pool` = null | UPSTREAM_NULL |
| `pool` 非 list | DATA_ARRAY_INVALID |

只有 `pool` 为 list 才进入行标准化。

## 10. Date-binding Semantics

检查 payload 中可识别的日期字段，候选键：`trade_date` / `date` / `qdate`。

日期值格式：`YYYY-MM-DD` / `YYYYMMDD`。

| 条件 | trade_date_match | 行为 |
|------|-----------------|------|
| 存在可解析日期且等于 requested | true | 继续 |
| 存在可解析日期但不等 | false | unavailable + TRADE_DATE_MISMATCH |
| 未提供可验证日期字段 | null | partial + DATE_BINDING_UNVERIFIED |

由于 Blocker 3 尚未关闭，`trade_date_match = null` 时不得伪造为 `true`。

非空有效 pool 且无日期字段时：`status = partial`，`reason_codes` 包含 `DATE_BINDING_UNVERIFIED`，`coverage_warning = true`。

不得在本轮升级历史日期绑定证据。

## 11. Universe Contract

唯一纳入代码前缀：`60xxxx / 00xxxx / 30xxxx / 68xxxx`。

明确排除：`4xxxxx / 8xxxxx / 920xxx / 9xxxxx / 200xxx / 900xxx`、ETF、LOF、可转债、基金、指数。

实现：先确认严格六位数字字符串，再 `stock_code.startswith(("60", "00", "30", "68"))`。

ST included、\*ST included。不得根据名称包含 ST/\*ST 排除记录。

被 universe 正常排除的合法行：不计 `invalid_row_count`，不导致 `partial`，计入 `excluded_universe_count`。

## 12. Row Normalization

来源字段：

- `stock_code`：优先读取 `c`，允许兼容 `code`
- `lbc`：读取 `lbc`

`stock_code`：必须为六位数字字符串，不得从 int 自动补零，不得整数化。

`lbc`：必须为 int，bool 不允许，必须 > 0，不得从缺失值默认成 1。

无效行：不进入 `rows`，`invalid_row_count += 1`，`status` 至少 `partial`，`reason_codes` 包含 `INVALID_POOL_ROW`，`coverage_warning = true`。

重复代码：保留首次合法且属于 universe 的记录，`duplicate_code_count += 1`，`reason_codes` 包含 `DUPLICATE_STOCK_CODE`，`coverage_warning = true`。

最终 `rows`：按 `stock_code` 严格升序，`stock_code` 唯一。

## 13. Empty and Legal-zero Semantics

`pool == []` 时：

```text
row_count = 0
rows = []
legal_zero = false
unexplained_empty = true
status = partial
reason_codes = ["UNEXPLAINED_EMPTY"]
coverage_warning = true
```

即使 HTTP 200 + JSON 正常 + `data.pool` 存在，也不得仅凭空数组设置 `legal_zero = true`。

本版 `legal_zero` 始终 `False`：本仓库尚无可信 final 快照生产者可独立证明"当日全市场确实无涨停"。

适配器已阻止空数组误判为合法零值，但 legal-zero 的正向确认仍依赖未来可信 final 生产者或明确来源证据。

因此 Blocker 6 是否完全关闭，需要结合 Blocker 5 的后续实现重新评估。

不得添加调用方布尔参数绕过该限制。

## 14. Status and Reason-code Matrix

| status | 条件 |
|--------|------|
| normal | 完全有效、非空、日期匹配 |
| partial | 有效但日期未验证 / 存在 invalid 或 duplicate / 空池 |
| unavailable | 输入无效 / 非交易日 / 传输失败 / HTTP 错误 / 解析失败 / 结构异常 / 日期不匹配 |

固定 reason-code 顺序：

```text
NON_TRADING_DATE
TRADING_CALENDAR_UNAVAILABLE
REQUEST_TIMEOUT
TRANSPORT_ERROR
RATE_LIMITED
ACCESS_RESTRICTED
HTTP_ERROR
PARSE_ERROR
UPSTREAM_NULL
REQUIRED_FIELD_MISSING
DATA_ARRAY_INVALID
TRADE_DATE_MISMATCH
DATE_BINDING_UNVERIFIED
INVALID_POOL_ROW
DUPLICATE_STOCK_CODE
UNEXPLAINED_EMPTY
```

## 15. Mapping to Layered Promotion Contract

本适配器为未来 layered promotion rates 计算提供标准化输入：

- `rows` 中的 `{stock_code, lbc}` 可直接用于跨日 numerator/denominator 计算
- `status` / `reason_codes` / `coverage_warning` 可用于上游数据质量门控
- `excluded_universe_count` / `invalid_row_count` / `duplicate_code_count` 提供数据清洗审计

但 `implementation_allowed(layered_promotion_rates) = false`，本轮不实现计算逻辑。

## 16. Blocker 6 Decision

**PARTIALLY CLOSED**

适配器已区分以下状态：

- legal zero（本版本始终 false，因无可信 final 生产者）
- 非交易日（NON_TRADING_DATE）
- 交易日历不可用（TRADING_CALENDAR_UNAVAILABLE）
- 传输超时（REQUEST_TIMEOUT）
- 传输错误（TRANSPORT_ERROR）
- 限流（RATE_LIMITED）
- 访问控制（ACCESS_RESTRICTED）
- HTTP 错误（HTTP_ERROR）
- JSON 解析失败（PARSE_ERROR）
- 上游 null（UPSTREAM_NULL）
- 结构异常（REQUIRED_FIELD_MISSING / DATA_ARRAY_INVALID）
- 日期不匹配（TRADE_DATE_MISMATCH）
- 日期绑定未验证（DATE_BINDING_UNVERIFIED）
- 无效行（INVALID_POOL_ROW）
- 重复代码（DUPLICATE_STOCK_CODE）
- 未解释空（UNEXPLAINED_EMPTY）

剩余：正向 legal-zero 证据依赖未来可信 final 快照生产者或明确来源证据。Blocker 6 完全关闭需要结合 Blocker 5 的后续实现重新评估。

## 17. Blocker 7 Decision

**CLOSED**

universe 合同已落地：

- `60xxxx / 00xxxx / 30xxxx / 68xxxx` 纳入
- `4xxxxx / 8xxxxx / 920xxx / 9xxxxx / 200xxx / 900xxx` 排除
- ST/\*ST included（不根据名称排除）
- 被排除行计入 `excluded_universe_count`，不计 `invalid_row_count`，不导致 `partial`
- 测试覆盖全部 12 种前缀 + ST/\*ST 名称场景

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
- 不提交 Cookie、Token 或 Authorization 值

## 20. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- 适配器实现了完整的失败关闭状态区分（Blocker 6 部分关闭）
- universe 合同完整落地（Blocker 7 关闭）
- 83 项测试全部通过，2224 项 backend 离线测试全部通过
- 无新增运行时依赖，不修改既有模块

剩余阻断：

- Blocker 5（legal_zero 正向证据）仍 OPEN
- Blocker 6 完全关闭依赖 Blocker 5
- Blocker 8/9 本轮未关闭
- `layered_promotion_rates` 实现仍不允许
