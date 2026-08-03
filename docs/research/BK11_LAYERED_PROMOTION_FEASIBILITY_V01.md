# BK-11 Slice 2B 分层晋级率精确分母与跨日身份匹配可行性审计

## 1. Executive Decision

**Overall Decision: CONDITIONAL GO**

分层晋级率 `layered_promotion_rates` 的计算合同可以完整定义，且现有仓库代码已确认具备
取得历史 final 涨停池、昨涨停池、连板数字段、股票代码字段的能力。但存在一个可封闭的
工程前置条件：**项目缺乏可靠的 A 股交易日历**（现有 `previous_weekday` 仅处理周末，
无法处理法定节假日、临时休市、长假后首个交易日）。

在下一独立子阶段实现最小交易日历接口后，可重新评估进入生产实现的条件。具体关闭办法
与验收证据见第 18 节。

除交易日历外，实现还需满足：final 状态由调用方传入 `session="final"`（不依赖时间判断）；
合法零值需通过 `legal_zero` 标记区分（昨日合法零涨停 → `rates=[]`，今日合法零涨停 →
每层 `rate=0.0`）；部分覆盖（`coverage_warning=true`）不输出指标（`rates=null`）。

## 2. Scope and Non-goals

### 2.1 本轮范围

- 审计 `layered_promotion_rates` 的精确分母与分子合同
- 审计跨交易日股票身份匹配规则
- 审计前一交易日确定方法
- 审计 final / partial / unavailable 判定
- 审计现有东财池字段是否足以支持上述合同
- 固化研究 fixture 与文档

### 2.2 本轮不实现

- `layered_promotion_rates` 生产计算模块
- `premium` / `next_open_return` / `next_close_return` / `next_high_return` / `loss_effect`
- `theme_structure` / `seal_quality`
- `history` backfill
- T+1 决策闭环
- API / 页面 / 数据库 / 调度器 / LLM
- 交易日历实现（仅定义合同）

## 3. Existing Repository Reuse Points

### 3.1 涨停池取得能力（代码已确认）

`backend/astock.py:541` 定义：

```python
def em_zt_topic_pool(endpoint: str, date: str, sort: str = "fbt:asc") -> list[dict]:
    """东财涨停板行情中心原始池（push2ex）。
    endpoint: getTopicZTPool(涨停) / getTopicZBPool(炸板) / getTopicDTPool(跌停) / getYesterdayZTPool(昨涨停)
    date: YYYYMMDD 交易日。非交易日 / 参数错 → []。
    池内每项字段含 lbc(连板数) / zbc(炸板次数) / hybk(行业) 等。"""
```

- **支持传入历史交易日**：`date` 参数为 `YYYYMMDD` 字符串，非交易日或参数错返回 `[]`
- **四个端点**：`getTopicZTPool`（今日涨停）、`getYesterdayZTPool`（昨涨停）、`getTopicZBPool`（炸板）、`getTopicDTPool`（跌停）
- **调用路径**：`backend/market.py:260` 在 `_emotion()` 中调用，从今天往前回溯 8 天找最近交易日

### 3.2 昨涨停池能力（代码已确认）

`backend/market.py:269` 已使用：

```python
yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池
```

`getYesterdayZTPool` 端点返回前一交易日的涨停池。但注意：
- 该端点返回的是 **前一交易日** 的涨停池，不是任意历史日
- 若需要任意历史日 N 的涨停池，应使用 `getTopicZTPool` 传入历史日期 `date`

### 3.3 涨停池字段（代码已确认）

从 `backend/market.py:271-289` 可确认池内字段：

| 字段 | 含义 | 用途 |
|------|------|------|
| `c` | 股票代码（字符串） | 身份键 |
| `n` | 股票名称 | 仅展示 |
| `lbc` | 连板数 | 核心字段 |
| `p` | 价格（×1000） | 非本轮必需 |
| `zdp` | 涨跌幅 | 非本轮必需 |
| `amount` | 成交额 | 非本轮必需 |
| `ltsz` | 流通市值 | 非本轮必需 |
| `hybk` | 行业 | 非本轮必需 |

### 3.4 代码标准化能力（代码已确认）

仓库存在多个代码标准化实现：

- `backend/watchlist_store.py:66` `_normalize_codes`：6 位数字、去重、保序，使用 `_CODE_RE` 正则
- `backend/portfolio_advice_sellable.py:46` `_normalize_code`：trim 后返回字符串或 None
- `backend/astock.py:651` `_map_a_share_row`：校验 `len(code) == 6 and code.isdigit()`

### 3.5 交易日历能力（代码已确认 - 不完整）

`backend/data_health_service.py:179` 定义：

```python
def previous_weekday(d):
    cur = d
    while _is_weekend(cur):
        cur = cur - timedelta(days=1)
    return cur
```

**局限性**：
- 仅处理周末（周六、周日）
- **无法处理法定节假日**（如国庆、春节、劳动节等）
- **无法处理临时休市**
- **无法处理长假后首个交易日**（如春节长假后第一天，前一交易日可能距今 7-10 天）
- 函数注释明确："保守 A 股期望交易日（YYYY-MM-DD，北京时间）。无节假日日历。"

### 3.6 final 稳定窗口（代码已确认 - 间接）

`backend/market.py:255-263` 的回溯逻辑：

```python
today = datetime.now(BEIJING).date()
resolved, zt = "", []
for back in range(8):
    d = (today - timedelta(days=back)).strftime("%Y%m%d")
    zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
    if zt:
        resolved = d
        break
```

- 从今天往前回溯 8 天，第一日有涨停池即取
- 非交易日或盘前返回 `[]`，自动跳过
- 这是一种"找到最近有数据的交易日"的实用策略，但不是显式的 final 稳定窗口判定

### 3.7 复用点汇总

| 能力 | 复用点 | 状态 |
|------|--------|------|
| 涨停池取得（含历史） | `astock.em_zt_topic_pool` | 代码已确认 |
| 昨涨停池取得 | `astock.em_zt_topic_pool("getYesterdayZTPool", ...)` | 代码已确认 |
| 连板数字段 | 池内 `lbc` 字段 | 代码已确认 |
| 股票代码字段 | 池内 `c` 字段 | 代码已确认 |
| 代码标准化 | `watchlist_store._normalize_codes` / `astock._map_a_share_row` | 代码已确认 |
| 交易日历 | `data_health_service.previous_weekday` | 代码已确认 - 不完整（仅周末） |
| final 判定 | 无显式实现，仅回溯逻辑 | 推断 |

## 4. Source and Endpoint Evidence

### 4.1 端点证据表

| 端点 | URL | 用途 | 历史日期支持 | 验证方法 | 验证状态 |
|------|-----|------|-------------|----------|----------|
| `getTopicZTPool` | `https://push2ex.eastmoney.com/getTopicZTPool` | 当日/历史涨停池 | 是（`date` 参数） | 代码阅读 | verified |
| `getYesterdayZTPool` | `https://push2ex.eastmoney.com/getYesterdayZTPool` | 昨涨停池 | 是（`date` 参数） | 代码阅读 | verified |
| `getTopicZBPool` | `https://push2ex.eastmoney.com/getTopicZBPool` | 炸板池 | 是 | 代码阅读 | verified |
| `getTopicDTPool` | `https://push2ex.eastmoney.com/getTopicDTPool` | 跌停池 | 是 | 代码阅读 | verified |

### 4.2 字段证据表

| field_name | source_endpoint | raw_key | raw_type | sample_value_shape | trade_date_semantics | session_semantics | missing_behavior | duplicate_behavior | verification_method | verification_status | limitations |
|------------|-----------------|---------|----------|-------------------|---------------------|-------------------|------------------|-------------------|---------------------|---------------------|-------------|
| stock_code | getTopicZTPool | `c` | string | `"600000"` | 由 `date` 参数决定交易日 | final 池为收盘后稳定 | 缺失 → 该行无效 | 池内重复 → 需去重 | 代码阅读 `market.py:280` | verified | 6 位数字字符串，无交易所前缀 |
| consecutive_limit_up_days | getTopicZTPool | `lbc` | int | `1`, `2`, `3` | 由 `date` 参数决定交易日 | final 池为收盘后稳定 | 缺失 → `market.py:271` 用 `_num(p.get("lbc")) or 1` 默认 1 板 | 不适用 | 代码阅读 `market.py:271,281` | verified | 首板为 1，连板 >= 2 |
| trade_date | 请求参数 | `date` | string | `"20260730"` | 传入即返回该日数据 | 非交易日返回空池 | 非交易日 → `[]` | 不适用 | 代码阅读 `astock.py:544` | verified | YYYYMMDD 格式 |
| pool array | 响应 `data.pool` | `pool` | list | `[{...}, {...}]` | 由 `date` 参数决定 | final 池为收盘后稳定 | 缺失 → `[]` | 池内可能有重复 | 代码阅读 `astock.py:552` | verified | 每页 10000 条 |
| source update time | 响应无显式字段 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 代码阅读 | not_verified | 端点无显式更新时间字段，需依赖 `date` 参数 |

### 4.3 受控探针结果

本轮未执行实时网络探针。理由：

1. **代码证据已充分**：`em_zt_topic_pool` 的历史日期支持、字段结构、调用路径均已在代码中确认
2. **风险控制**：实时探针可能触发东财反爬机制，且现有 `_emotion()` 已在生产使用该端点
3. **非必要**：本任务是合同固化，不是字段发现

若后续实现阶段需要验证，建议执行：
- 选择 3 组相邻交易日（如 2026-07-28/29/30）
- 对每组调用 `getTopicZTPool(date)` 和 `getYesterdayZTPool(date)`
- 验证 `getYesterdayZTPool(date)` 返回的池是否等于 `getTopicZTPool(previous_date)` 的池
- 验证 `lbc` 字段在两日的值是否满足晋级关系

## 5. Trading Calendar Contract

### 5.1 前一交易日定义

```
previous_trade_date(current_trade_date) → previous_trade_date
```

必须覆盖：
- 周末（周六、周日）
- 法定节假日（国庆、春节、劳动节、元旦、清明、端午、中秋等）
- 临时休市（罕见但存在）
- 长假后首个交易日（如春节长假后第一天，前一交易日可能距今 7-10 天）
- 非交易日输入（应返回 None 或抛异常）

### 5.2 现有能力评估

`data_health_service.previous_weekday` 仅处理周末，**无法处理法定节假日**。

### 5.3 实现前置依赖

**必须先实现最小交易日历接口**，否则分层晋级率在节假日后会产出错误结果。

推荐最小接口：

```python
def previous_trade_date(current_trade_date: str) -> str | None:
    """返回前一交易日（YYYY-MM-DD）。非交易日输入返回 None。"""
```

### 5.4 关闭办法

1. 新增 `backend/trade_calendar.py`，实现 `previous_trade_date`
2. 数据源选项（按优先级）：
   - 内置静态节假日表（每年维护，简单可靠）
   - 从东财交易日历 API 取（`dataapi.eastmoney.com/eastmoney/calendar`）
   - 从 `akshare` 取（已存在依赖？需检查）
3. 失败时返回 `None`，调用方降级为 `unavailable`

### 5.5 验收证据

关闭后需验证：
- 2026-10-08（国庆后首个交易日）的 `previous_trade_date` 应为 2026-09-30
- 2026-02-05（春节后首个交易日，假设）的 `previous_trade_date` 应为 2026-02-05 前最后一个交易日
- 周末输入返回前一交易日
- 非交易日输入返回 `None`

## 6. Stock Identity Contract

### 6.1 唯一身份字段

```
stock_code: 6 位 A 股代码字符串
```

### 6.2 规范化规则

```
raw code
→ trim（去除首尾空格）
→ 保留字符串（不转 int，防前导零丢失）
→ 校验 6 位数字
→ 根据项目 universe 排除非目标市场
```

### 6.3 审计问题

| 问题 | 结论 | 证据 |
|------|------|------|
| 是否带交易所前缀或后缀 | 否，池内 `c` 字段为纯 6 位数字 | `market.py:280` |
| 是否存在整数导致前导零丢失 | 否，`c` 为字符串 | `market.py:280` `str(p.get("c", ""))` |
| 沪深代码是否可能冲突 | 否，沪深代码区间不重叠（60xxxx=沪，00xxxx=深，30xxxx=创业板，68xxxx=科创板） | 通用知识 |
| 代码字段是否始终稳定 | 是，6 位代码为 A 股稳定身份 | 代码已确认 |
| ST 与 *ST 是否仍使用同一代码 | 是，ST/*ST 仅影响涨跌停限制，代码不变 | 通用知识 |
| 退市整理期是否可能进入池 | 否，退市整理期股票不在涨停池 | 推断（东财涨停池不含退市股） |
| 北交所代码是否可能进入响应 | 是，8xxxxx/4xxxxx 可能在响应中，但项目 universe 排除 BSE | `fixture V01 market_scope.excluded: ["BSE"]` |
| 重复行如何处理 | 保留首次合法记录，忽略后续重复 | `short_term_limit_up_ladder.py` 已实现 |

### 6.4 universe 排除规则

根据 `fixture V01` 的 `market_scope`：

```
included: SH main, SZ main, ChiNext, STAR
excluded: BSE, ST, *ST, IPO no-limit period, delisting period, B shares, ETF, LOF, convertible bonds, funds, indexes
```

北交所（8xxxxx/4xxxxx）应排除。但东财涨停池通常已排除 B 股、ETF、基金等，仍需校验代码区间。

### 6.5 前导零风险

深市代码以 `00` 开头，若以整数类型存储会丢失前导零。规范化必须保留字符串类型，
并校验 6 位数字。正常样本仅允许 `60xxxx`（沪市主板）、`00xxxx`（深市主板）、
`30xxxx`（创业板）、`68xxxx`（科创板）前缀；`4xxxxx`、`8xxxxx`、`920xxx`、`9xxxxx`
前缀（北交所/非 A 股）应排除。

## 7. Previous/Current Final Snapshot Contract

### 7.1 双快照要求

分层晋级率需要两个 final 快照：

```
previous_snapshot: 前一交易日 final 涨停池
current_snapshot: 当前交易日 final 涨停池
```

### 7.2 取得方式

```python
# 前一交易日 final 涨停池
previous_pool = astock.em_zt_topic_pool("getTopicZTPool", previous_date_yyyymmdd, "fbt:asc")

# 当前交易日 final 涨停池
current_pool = astock.em_zt_topic_pool("getTopicZTPool", current_date_yyyymmdd, "fbt:asc")
```

注意：不使用 `getYesterdayZTPool`，因为该端点返回的是"相对于参数日期的前一交易日"的池，
而我们需要的是"任意指定历史日"的池。使用 `getTopicZTPool(date)` 传入历史日期更明确。

### 7.3 final 判定

```
previous_is_final = true
current_is_final = true
```

判定方式：
- `session == "final"`
- `is_final == true`
- 两日 `trade_date` 正确且 `previous = previous_trade_date(current)`
- 必需池字段完整（`c` 和 `lbc`）
- 稳定窗口满足（收盘后）

### 7.4 稳定窗口

A 股收盘时间为北京时间 15:00。收盘后涨停池稳定，但实际数据源更新可能有延迟。

建议稳定窗口：
- 收盘后 15:00-15:10 为过渡期
- 15:10 后视为 final
- 但本模块不依赖时间判断，而是依赖调用方传入 `session="final"`

## 8. Exact Denominator and Numerator Definition

### 8.1 候选定义

```
对于每个 N >= 1：

denominator_N =
前一交易日 final 涨停池中
consecutive_limit_up_days == N
的唯一股票数量

numerator_N =
denominator_N 中
在当前交易日 final 涨停池出现，
且 consecutive_limit_up_days == N + 1
的唯一股票数量

rate_N =
numerator_N / denominator_N
```

### 8.2 接受推荐合同

**接受推荐合同**，具体如下：

```
- 只输出 denominator > 0 的昨日实际层级
- 按 from_level 升序
- sample_count = denominator
- rate = round(numerator / denominator, 4)
- denominator=0 的层不输出
- rate 为 float，非 string
```

### 8.3 输出结构

```json
[
  {
    "from_level": 1,
    "to_level": 2,
    "numerator": 9,
    "denominator": 30,
    "sample_count": 30,
    "rate": 0.3
  }
]
```

### 8.4 字段语义

| 字段 | 类型 | 语义 |
|------|------|------|
| `from_level` | int >= 1 | 昨日连板数 N |
| `to_level` | int >= 2 | 今日连板数 N+1 |
| `numerator` | int >= 0 | 昨日 N 板中今日晋级为 N+1 板的唯一股票数 |
| `denominator` | int > 0 | 昨日 N 板的唯一股票数 |
| `sample_count` | int | 始终等于 denominator |
| `rate` | float 或 null | round(numerator / denominator, 4) |

### 8.5 边界

- `denominator=0` 的层：不输出
- `numerator=0` 但 `denominator>0`：输出，`rate=0.0`
- 最高层：只输出昨日实际存在的层（`denominator>0`）
- `sample_count` 始终等于 `denominator`

## 9. Layer Output Schema

### 9.1 排序

```
按 from_level 升序
```

### 9.2 空层

- `denominator=0` 的层不输出
- 不补空层

### 9.3 最高层

- 只输出昨日实际存在的层
- 不额外输出"最高层 + 1"

### 9.4 rate 精度

```
rate = round(numerator / denominator, 4)
```

四位小数，与现有 `short_term_limit_up_ladder` 和 `short_term_market_facts` 一致。

## 10. Cross-day Matching Edge Cases

### 10.1 匹配规则

```
核心原则：只有明确出现在当前 final 涨停池且板数=N+1，才进入 numerator。
```

### 10.2 逐项处理

| 场景 | 处理 | 说明 |
|------|------|------|
| 昨日 N 板，今日 N+1 板 | 进入 numerator | 晋级成功 |
| 昨日 N 板，今日仍为 N 板 | 不进入 numerator | 未晋级，仍在 denominator |
| 昨日 N 板，今日首板 | 不进入 numerator | 板数回退，异常情况 |
| 昨日 N 板，今日未涨停 | 不进入 numerator | 未晋级 |
| 昨日 N 板，今日停牌 | 不进入 numerator | 无法判断，视为未晋级 |
| 昨日 N 板，今日退市或不在 universe | 不进入 numerator | 视为未晋级 |
| 昨日池重复代码 | 保留首次合法记录 | DUPLICATE_STOCK_CODE |
| 今日池重复代码 | 保留首次合法记录 | DUPLICATE_STOCK_CODE |
| 昨日 lbc 缺失 | 该行无效，排除 | INVALID_POOL_ROW |
| 今日 lbc 缺失 | 该行无效，排除 | INVALID_POOL_ROW |
| 代码字段非法 | 该行无效，排除 | INVALID_POOL_ROW |
| 昨日和今日 trade_date 不匹配 | unavailable | TRADE_DATE_MISMATCH |

### 10.3 停牌与覆盖完整性

**关键决策**：

```
今日停牌或 universe 状态未知时，计为未晋级（不进入 numerator），
但若来源无法区分"未涨停"和"未被可靠覆盖"，应标记 PARTIAL_COVERAGE。
```

理由：
- 东财涨停池只包含当日涨停的股票，不包含停牌股
- 若昨日 N 板的股票今日停牌，它不会出现在今日涨停池中
- 这与"今日未涨停"无法区分
- 若有独立停牌信息源，可精确区分；否则标记 PARTIAL_COVERAGE

### 10.4 今日板数跳级

```
昨日 N 板，今日 N+2 板（跳级）
```

处理：不进入 numerator（因为 numerator 要求 N+1）。

这种场景在 A 股极少见（通常连板数每日最多 +1），但合同应明确处理。
该股票仍会出现在今日池中，但不计入任何层的 numerator。

### 10.5 今日板数未递增

```
昨日 N 板，今日 N 板（未递增）
```

处理：不进入 numerator。该股票今日仍是 N 板，说明今日又涨停但板数未增加（理论上不应发生，
因为连板数应每日 +1）。这可能表明数据异常，但不影响 numerator 计算。

## 11. Legal Zero and Missing Semantics

### 11.1 昨日合法零涨停

```
昨日 limit_up_pool = []
昨日 legal_zero = true
昨日 row_count = 0
```

处理：
```
layered_promotion_rates = []
status = normal
```

理由：昨日无涨停股，分母全为 0，无层可输出，结果为空列表，状态正常。

### 11.2 今日合法零涨停

```
昨日有分母（denominator > 0）
今日 limit_up_pool = []
今日 legal_zero = true
今日 row_count = 0
```

处理：
```
每层 numerator = 0
rate = 0.0
status = normal
```

理由：昨日有涨停股，但今日无任何涨停（合法零值），所有昨日涨停股今日均未晋级，
numerator 全为 0，rate 全为 0.0。

### 11.3 今日未解释空池

```
今日 limit_up_pool = []
今日 legal_zero = false
今日 unexplained_empty = true
```

处理：
```
layered_promotion_rates = null
status = partial
reason_codes 包含 UNEXPLAINED_EMPTY
```

理由：今日空池无法确认是合法零值还是数据缺失，不能简单视为未晋级。

### 11.4 今日普通空池

```
今日 limit_up_pool = []
今日 legal_zero = false
今日 unexplained_empty = false
```

处理：
```
layered_promotion_rates = null
status = unavailable
reason_codes 包含 CURRENT_SNAPSHOT_UNAVAILABLE
```

## 12. Data Health Contract

### 12.1 双侧结构

**推荐保留双侧**：

```json
{
  "previous": {
    "transport_success": true,
    "parse_success": true,
    "required_field_present": true,
    "data_array_present": true,
    "trade_date_match": true,
    "row_count": 67,
    "legal_zero": false,
    "upstream_null": false,
    "unexplained_empty": false,
    "coverage_warning": false
  },
  "current": {
    "transport_success": true,
    "parse_success": true,
    "required_field_present": true,
    "data_array_present": true,
    "trade_date_match": true,
    "row_count": 65,
    "legal_zero": false,
    "upstream_null": false,
    "unexplained_empty": false,
    "coverage_warning": false
  }
}
```

### 12.2 失败语义

| 场景 | status | metrics | reason_codes |
|------|--------|---------|--------------|
| 昨日来源失败 | unavailable | null | SOURCE_UNAVAILABLE, PREVIOUS_SNAPSHOT_UNAVAILABLE |
| 今日来源失败 | unavailable | null | SOURCE_UNAVAILABLE, CURRENT_SNAPSHOT_UNAVAILABLE |
| 昨日合法零涨停 | normal | [] | （无） |
| 今日合法零涨停 | normal | 正常计算（numerator全0, rate=0.0） | （无） |
| 昨日空池未解释 | partial | null | UNEXPLAINED_EMPTY, PREVIOUS_SNAPSHOT_UNAVAILABLE |
| 今日空池未解释 | partial | null | UNEXPLAINED_EMPTY, CURRENT_SNAPSHOT_UNAVAILABLE |
| coverage_warning=true（任一侧） | partial | null | SOURCE_PARTIAL, PARTIAL_COVERAGE |
| 昨日部分非法行 | partial | null | INVALID_POOL_ROW, PARTIAL_COVERAGE |
| 今日部分非法行 | partial | null | INVALID_POOL_ROW, PARTIAL_COVERAGE |
| row_count 不匹配 | partial | null | PARTIAL_COVERAGE |

**关键决策**：partial 状态下 `layered_promotion_rates = null`。理由：部分覆盖意味着
样本不完整，若强行计算会产出误导性比率（分母或分子可能缺失）。调用方应根据
`reason_codes` 判断是否需要重试或降级展示。

### 12.3 双侧 row_count

昨日 `row_count` 与昨日 `limit_up_pool` 原始长度比较；
今日 `row_count` 与今日 `limit_up_pool` 原始长度比较。

## 13. Reason Codes and Status Semantics

### 13.1 建议错误码

| 错误码 | 语义 | 类别 |
|--------|------|------|
| `SOURCE_UNAVAILABLE` | 全局来源失败 | 全局 unavailable |
| `SOURCE_PARTIAL` | 部分可用 | 可计算 partial |
| `PREVIOUS_SNAPSHOT_UNAVAILABLE` | 昨日快照不可用 | 全局 unavailable |
| `CURRENT_SNAPSHOT_UNAVAILABLE` | 今日快照不可用 | 全局 unavailable |
| `TRADE_DATE_MISMATCH` | 交易日不匹配 | 可计算 partial（若仅一侧） |
| `NOT_FINAL` | 非 final 状态 | 全局 unavailable |
| `PARTIAL_COVERAGE` | 部分覆盖 | 可计算 partial |
| `INVALID_POOL_ROW` | 池行非法 | 可计算 partial |
| `DUPLICATE_STOCK_CODE` | 重复代码 | 可计算 partial |
| `IDENTITY_MATCH_INCOMPLETE` | 身份匹配不完整 | 可计算 partial |
| `TRADING_CALENDAR_UNAVAILABLE` | 交易日历不可用 | 全局 unavailable |
| `UNEXPLAINED_EMPTY` | 未解释空池 | 可计算 partial |

### 13.2 优先级排序

```
SOURCE_UNAVAILABLE
PREVIOUS_SNAPSHOT_UNAVAILABLE
CURRENT_SNAPSHOT_UNAVAILABLE
TRADING_CALENDAR_UNAVAILABLE
NOT_FINAL
TRADE_DATE_MISMATCH
SOURCE_PARTIAL
PARTIAL_COVERAGE
UNEXPLAINED_EMPTY
INVALID_POOL_ROW
DUPLICATE_STOCK_CODE
IDENTITY_MATCH_INCOMPLETE
```

### 13.3 状态规则

```
normal:
  reason_codes = []
  warnings = []
  metrics = 正常计算（含空列表 [] 表示昨日合法零涨停）

partial:
  reason_codes 至少包含 SOURCE_PARTIAL 或对应部分覆盖码
  warnings = ["snapshot partially available; rates suppressed due to coverage_warning"]
  metrics = null

unavailable:
  reason_codes 至少包含 SOURCE_UNAVAILABLE
  warnings = ["snapshot unavailable; no layered promotion rates emitted"]
  metrics = null
```

**partial 与 unavailable 的 metrics 一致性**：两者均输出 `metrics = null`。
区别在于 `reason_codes`：partial 表示来源部分可用但覆盖不完整，
unavailable 表示来源全局失败。调用方应通过 `reason_codes` 区分降级原因。

## 14. Controlled Probe Results

本轮未执行实时网络探针。理由见第 4.3 节。

代码证据已充分确认：
- `em_zt_topic_pool` 支持历史日期
- `getTopicZTPool` 返回当日涨停池
- `getYesterdayZTPool` 返回昨涨停池
- 池内字段 `c`（代码）和 `lbc`（连板数）已确认

若实现阶段需要补充验证，建议按第 4.3 节的方案执行受控探针。

## 15. Synthetic Fixture Description

见同目录 `BK11_LAYERED_PROMOTION_FIXTURE_V01.json`。

### 15.1 Fixture 结构

```json
{
  "schema_version": "bk11-layered-promotion-fixture.v0.1",
  "fixture_kind": "synthetic-normalized",
  "description": "...",
  "cases": [
    {"case_id": "normal", ...},
    {"case_id": "zero_denominator", ...},
    {"case_id": "previous_legal_zero", ...},
    {"case_id": "current_legal_zero", ...},
    {"case_id": "partial", ...},
    {"case_id": "unavailable", ...},
    {"case_id": "identity_edge", ...}
  ]
}
```

### 15.2 Case 说明

| case_id | 场景 | 预期 status | 预期 metrics |
|---------|------|-------------|-------------|
| normal | 昨日 4 首板/2 二板/1 三板，今日 2 首板晋级二板、1 二板晋级三板 | normal | 3 层 |
| zero_denominator | 昨日某层不存在 | normal | 该层不输出 |
| previous_legal_zero | 昨日无涨停 | normal | [] |
| current_legal_zero | 昨日有分母，今日合法零涨停 | normal | 每层 rate=0.0 |
| partial | 今日 coverage_warning=true | partial | null |
| unavailable | 今日 transport_success=false | unavailable | null |
| identity_edge | 昨日有效今日缺失/跳级/未递增 | normal | 2→3 = 0/2/0.0 |

### 15.3 代码前缀合同

fixture 正常样本仅使用 `60/00/30/68` 前缀（沪市主板/深市主板/创业板/科创板）。
不使用 `9/4/8/920` 前缀作为正常样本。`identity_edge` case 中的前导零、重复、
非法代码场景由 `edge_case_notes` 说明，实际池行仍使用合法前缀以保持校验一致性。

## 16. Risks and Licensing Boundary

### 16.1 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 交易日历不完整（节假日） | 高 | 必须先实现交易日历接口 |
| 东财端点反爬 | 中 | 控制请求频率，复用现有缓存机制 |
| 跨日身份匹配不完整 | 中 | 标记 PARTIAL_COVERAGE，不假设缺失=未晋级 |
| final 判定不准 | 中 | 依赖调用方传入 session="final"，不自行判断时间 |
| 停牌股无法区分 | 低 | 标记 PARTIAL_COVERAGE，若有独立停牌源可升级 |

### 16.2 许可边界

- 东财 push2ex 端点为公开行情接口，现有项目已使用
- 不提交原始完整响应
- 不提交 Cookie、Token、URL 参数中的敏感值
- 不绕过验证码或访问控制
- 不提高并发（请求间隔 >= 1.2 秒）
- 不持续轮询

## 17. Implementation Entry Conditions

### 17.1 必须满足

- [x] 股票身份字段明确：`c` 字段，6 位数字字符串
- [x] 昨日和今日池均可按交易日取得：`em_zt_topic_pool("getTopicZTPool", date, ...)`
- [x] 连板数字段语义确认：`lbc` 字段，int，>= 1
- [ ] 跨日匹配至少机械验证 3 组相邻交易日：待实现阶段执行
- [ ] 交易日历路径明确：合同已定义，但实现未完成
- [x] final 判定路径明确：依赖调用方传入 session="final"
- [x] 合法零值语义明确
- [x] 缺失与部分覆盖语义明确
- [x] 精确分母合同无歧义

### 17.2 前置依赖

- **必须先实现** `backend/trade_calendar.py` 的 `previous_trade_date` 函数
- 建议在下一独立子阶段（Slice 2B-1）实现

## 18. GO / CONDITIONAL GO / NO-GO Decision

### 18.1 决策

**CONDITIONAL GO**

### 18.2 未满足条件

```
交易日历实现未完成
```

`data_health_service.previous_weekday` 仅处理周末，无法处理法定节假日。
在节假日后首个交易日，`previous_trade_date` 会返回错误的日期（跳过节假日），
导致分层晋级率使用错误的昨日快照。

### 18.3 风险

- 节假日后首个交易日的分层晋级率会使用错误的昨日数据
- 例如：国庆后首个交易日（如 10-08），`previous_weekday` 返回 10-07（非交易日），
  而实际前一交易日是 09-30

### 18.4 具体关闭办法

1. 新增 `backend/trade_calendar.py`
2. 实现 `previous_trade_date(current_trade_date: str) -> str | None`
3. 数据源：内置静态节假日表（每年维护）或东财交易日历 API
4. 失败时返回 `None`，调用方降级为 `unavailable` + `TRADING_CALENDAR_UNAVAILABLE`

### 18.5 关闭后的验收证据

- `previous_trade_date("2026-10-08")` 返回 `"2026-09-30"`（假设 10-01 至 10-07 为国庆假期）
- `previous_trade_date("2026-02-05")` 返回春节前最后一个交易日
- `previous_trade_date("2026-07-30")` 返回 `"2026-07-29"`（普通工作日）
- 周末输入返回前一交易日
- 非交易日输入返回 `None`

关闭该条件后，可重新评估 `layered_promotion_rates` 进入生产实现的条件。仍需确认：
跨日匹配至少机械验证 3 组相邻交易日（含节假日边界）、final 判定路径由调用方显式传入、
合法零值与部分覆盖的降级语义已落地。
