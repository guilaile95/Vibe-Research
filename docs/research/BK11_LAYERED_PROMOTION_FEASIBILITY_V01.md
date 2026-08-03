# BK-11 Slice 2B 分层晋级率精确分母与跨日身份匹配可行性审计

## 1. Executive Decision

```
overall: CONDITIONAL GO
implementation_allowed: false
```

**结论**：

- 计算公式合同已经可以定义；
- 来源、日历、final、适配器和跨日验证尚未闭合；
- 当前不得进入 `layered_promotion_rates` 生产实现。

不得保留任何等价暗示（如"调用方传入 final 后即可实现"、"交易日历完成后即可实现"、
"关闭某一个条件后即可直接生产"）。

完整阻断条件清单见第 17.1 节（Implementation Entry Conditions）与第 18.2 节（最终
Decision），三处使用同一份九项清单，不得在某一章节勾选已满足而在另一章节又列为未满足。

universe 合同：本审计以已批准的 Slice 0 可行性文档 universe 表为权威合同。
Slice 0 fixture 中 ST/*ST excluded 属既有不一致，不在本轮采用，也不构成新的 universe
决策。ST/*ST 状态不由股票代码前缀决定；ST/*ST 是否进入分母会直接改变 denominator。
本轮无新证据支持偏离 Slice 0，因此保持 included。

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

仓库按"昨涨停池"用途调用 `getYesterdayZTPool`（调用路径与使用目的已确认）。

根据端点命名，预期其表示前一交易日相关池；但真实日期关系尚未完成机械验证，
当前状态为 `not_verified`。

在完成阻断条件 4 前，不得将该端点作为精确 previous-day 分母来源。
若需要任意历史日 N 的涨停池，应使用 `getTopicZTPool` 传入历史日期 `date`。

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
| 涨停池取得（含历史） | `astock.em_zt_topic_pool` | verified（函数存在、date 参数被传递） |
| 昨涨停池取得 | `astock.em_zt_topic_pool("getYesterdayZTPool", ...)` | verified（仓库使用） |
| 连板数字段 | 池内 `lbc` 字段 | verified as repository usage（上游类型 partially_verified） |
| 股票代码字段 | 池内 `c` 字段 | verified as repository usage（上游类型 partially_verified） |
| 代码标准化 | `watchlist_store._normalize_codes` / `astock._map_a_share_row` | verified |
| 交易日历 | `data_health_service.previous_weekday` | verified - 不完整（仅周末） |
| final 判定 | 无显式实现，仅回溯逻辑 | not_verified（无可信 final 生产者） |

## 4. Source and Endpoint Evidence

证据状态必须区分三类：仓库使用（repository usage）、上游类型（upstream type）、
上游语义（upstream semantics）。代码阅读只能确认仓库使用，不能直接确认上游语义。

### 4.1 端点证据表

| 端点 | URL | 用途 | 历史日期支持 | 验证方法 | 验证状态 |
|------|-----|------|-------------|----------|----------|
| `getTopicZTPool` | `https://push2ex.eastmoney.com/getTopicZTPool` | 当日/历史涨停池 | 仓库传递 `date` 参数 | 代码阅读 | verified（函数存在、date 参数被传递） |
| `getYesterdayZTPool` | `https://push2ex.eastmoney.com/getYesterdayZTPool` | 昨涨停池 | 仓库传递 `date` 参数 | 代码阅读 | verified（仓库使用） |
| `getTopicZBPool` | `https://push2ex.eastmoney.com/getTopicZBPool` | 炸板池 | 仓库传递 `date` 参数 | 代码阅读 | verified（仓库使用） |
| `getTopicDTPool` | `https://push2ex.eastmoney.com/getTopicDTPool` | 跌停池 | 仓库传递 `date` 参数 | 代码阅读 | verified（仓库使用） |

注：`verified` 仅指仓库使用层面。`getTopicZTPool` 历史日期可用性为
`partially_verified`（见 4.3 reviewer-provided probe）；`getYesterdayZTPool`
与指定前一交易日池的关系为 `not_verified`。

### 4.2 字段证据表

| field_name | source_endpoint | raw_key | raw_type | sample_value_shape | trade_date_semantics | session_semantics | missing_behavior | duplicate_behavior | verification_method | verification_status | limitations |
|------------|-----------------|---------|----------|-------------------|---------------------|-------------------|------------------|-------------------|---------------------|---------------------|-------------|
| stock_code | getTopicZTPool | `c` | string（仓库读取） | `"600000"` | 由 `date` 参数决定交易日 | final 池为收盘后稳定（未验证） | 缺失 → 该行无效 | 池内重复 → 需去重 | 代码阅读 `market.py:280` | partially_verified（仓库使用 verified；上游完整语义 not_verified） | 6 位数字字符串，无交易所前缀 |
| consecutive_limit_up_days | getTopicZTPool | `lbc` | int（仓库读取） | `1`, `2`, `3` | 由 `date` 参数决定交易日 | final 池为收盘后稳定（未验证） | 缺失 → `market.py:271` 用 `_num(p.get("lbc")) or 1` 默认 1 板 | 不适用 | 代码阅读 `market.py:271,281` | partially_verified（仓库使用 verified；上游类型 partially_verified；首板/连板及跨日晋级语义 not_verified） | 首板为 1，连板 >= 2 |
| trade_date | 请求参数 | `date` | string | `"20260730"` | 传入即返回该日数据 | 非交易日返回空池（未验证） | 非交易日 → `[]`（未验证） | 不适用 | 代码阅读 `astock.py:544` | partially_verified | YYYYMMDD 格式 |
| pool array | 响应 `data.pool` | `pool` | list | `[{...}, {...}]` | 由 `date` 参数决定 | final 池为收盘后稳定（未验证） | 缺失 → `[]` | 池内可能有重复 | 代码阅读 `astock.py:552` | partially_verified | 每页 10000 条 |
| source update time | 响应无显式字段 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 代码阅读 | not_verified | 端点无显式更新时间字段，需依赖 `date` 参数 |
| empty array semantics | 响应 `data.pool == []` | N/A | list | `[]` | N/A | N/A | N/A | N/A | 未验证 | not_verified | `[]` 可能代表合法零涨停/非交易日/请求失败/解析失败/限流/访问控制，适配器尚未能区分 |

### 4.3 受控探针结果

```
probes_performed_by_Q = 0
```

Q 本轮未执行实时网络探针，不得声称自行复验了以下结果。

#### reviewer-provided evidence（not independently re-run by Q）

审查者提供了以下历史探针结果（Q 未独立复验）：

```
getTopicZTPool("20260729") → 81 rows
getTopicZTPool("20260730") → 52 rows
getYesterdayZTPool("20260730") → 0 rows
```

该证据的覆盖范围明确如下：

- 仅支持 `getTopicZTPool` 历史日期参数 `partially_verified`（两个历史日期返回了非空池）
- **不证明** `getYesterdayZTPool` 的前一交易日关系（返回 0 rows，语义未确认）
- **不证明** 空数组是合法零值（`getYesterdayZTPool("20260730") → 0 rows` 可能是
  非交易日、请求失败、限流、访问控制或参数错误）
- **未完成** 3 组相邻交易日的跨日身份与 lbc 晋级关系机械验证

#### 实现阶段需补充的验证

若后续实现阶段需要验证，建议执行：
- 选择 3 组相邻交易日（含节假日边界）
- 对每组调用 `getTopicZTPool(date)` 和 `getYesterdayZTPool(date)`
- 验证 `getYesterdayZTPool(date)` 返回的池是否等于 `getTopicZTPool(previous_date)` 的池
- 验证 `lbc` 字段在两日的值是否满足晋级关系

## 5. Trading Calendar Contract

### 5.1 前一交易日定义

```
previous_trade_date(current_trade_date: str) -> str | None
```

时区：`Asia/Shanghai`。

`current_trade_date` 必须是已确认交易日。不得自动把任意非交易日先向前滚动，
再继续求前一交易日。

返回值语义：
- 非法格式 → `None`
- 非交易日输入 → `None`
- 来源不可用 → `None`
- 超出覆盖年份 → `None`
- 未来日期 → `None`
- 已确认交易日 → 前一交易日（YYYY-MM-DD）

必须覆盖：
- 周末（周六、周日）
- 法定节假日（国庆、春节、劳动节、元旦、清明、端午、中秋等）
- 临时休市（罕见但存在）
- 长假后首个交易日（如春节长假后第一天，前一交易日可能距今 7-10 天）

### 5.2 现有能力评估

`data_health_service.previous_weekday` 仅处理周末，**无法处理法定节假日**。

### 5.3 实现前置依赖

**必须先实现最小交易日历接口**，否则分层晋级率在节假日后会产出错误结果。

推荐最小接口：

```python
def previous_trade_date(current_trade_date: str) -> str | None:
    """返回前一交易日（YYYY-MM-DD）。非交易日输入返回 None。"""
```

### 5.4 下一阶段必须选择唯一方案

下一阶段必须选择唯一方案，并记录以下字段：

```
data source
licensing boundary
supported years
future-year behavior
update mechanism
offline test strategy
source-unavailable semantics
```

### 5.5 验收证据

具体日期案例必须等唯一日历源选定后再固化。本轮不采用任何无来源的具体日期案例。

可改成抽象测试：

```
长假后第一个已确认交易日
→ 返回假期前最后一个已确认交易日
```

```
普通相邻工作日（无节假日）
→ 返回前一个工作日
```

```
周末输入
→ 返回 None（非交易日输入）
```

```
非交易日输入
→ 返回 None
```

已删除以下事实错误或无来源的确定性案例（不得仅加"假设"后继续作为验收案例）：

- 春节后首个交易日的具体日期假设
- 国庆后首个交易日返回节前最后交易日的具体日期案例

具体日期必须等唯一日历源选定后再固化。

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
| 北交所代码是否可能进入响应 | 是，4xxxxx/8xxxxx/920xxx 可能在响应中，但项目 universe 排除 BSE | 代码前缀仅用于辅助校验，长期市场身份由明确的交易所和 universe 规则决定 |
| 重复行如何处理 | 保留首次合法记录，忽略后续重复 | `short_term_limit_up_ladder.py` 已实现 |

### 6.4 universe 合同

本审计以已批准的 Slice 0 可行性文档 universe 表为权威合同。
Slice 0 fixture 中 ST/*ST excluded 属既有不一致，不在本轮采用，也不构成新的 universe 决策。

```
included: SH main, SZ main, ChiNext, STAR, ST, *ST
excluded: BSE, IPO no-limit period, delisting period, B shares, ETF, LOF, convertible bonds, funds, indexes
```

ST/*ST 状态不由股票代码前缀决定。ST/*ST 是否进入分母会直接改变 denominator。
本轮无新证据支持偏离 Slice 0，因此保持 included。

北交所（`4xxxxx`、`8xxxxx`、`920xxx`）应排除。代码前缀仅为辅助校验；
长期市场身份应由明确的目标交易所/universe 规则决定，不能只依赖前缀。

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

注意：不使用 `getYesterdayZTPool` 作为精确 previous-day 分母来源。根据端点命名，
预期其表示前一交易日相关池，但真实日期关系尚未完成机械验证（`not_verified`，
见阻断条件 4）；在验证完成前，需要"任意指定历史日"的池时使用
`getTopicZTPool(date)` 传入历史日期更明确。

### 7.3 可信 final 合同

```
仓库当前不存在已验证的 layered-promotion final snapshot producer。
调用方传入 session="final" 或 is_final=true 只是声明，不能证明来源快照已 final。
```

实施前置条件必须包括：

```
previous snapshot final producer
current snapshot final producer
trade_date 来源校验
必需字段完整性校验
连续稳定窗口
失败和超时语义
```

只有以下条件全部成立才允许计算：

```
previous.session == final
previous.is_final == true
current.session == final
current.is_final == true
两侧 trade_date 正确
两侧字段完整
两侧稳定窗口满足
```

以下状态均不得计算：

```
pre_open
call_auction
morning_session
midday_break
afternoon_session
close_pending
仅时间 >= 15:00
调用方任意布尔声明
```

### 7.4 稳定窗口

A 股收盘时间为北京时间 15:00。收盘后涨停池稳定，但实际数据源更新可能有延迟。

稳定窗口判定属于 final 生产者职责，尚未实现。本模块不依赖时间判断，也不把调用方传入
`session="final"` 当作可信 final 证据。

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

### 11.1 空数组的歧义性

现有 `em_zt_topic_pool(...) → []` 可能代表：

```
合法零涨停
非交易日
请求失败
解析失败
限流
访问控制
参数错误
字段缺失
```

因此：

```
仅凭 [] 不得设置 legal_zero=true。
```

合法零值适配器生产者尚未存在，列为阻断条件（见第 17.1 节）。

### 11.2 适配器前置条件

未来适配器至少输出：

```
transport_success
parse_success
required_field_present
data_array_present
trade_date_match
row_count
legal_zero
upstream_null
unexplained_empty
coverage_warning
```

只有适配器可靠确认 `legal_zero=true`，才允许按以下规则处理。

### 11.3 昨日合法零涨停

```
昨日 limit_up_pool = []
昨日 legal_zero = true（适配器确认）
昨日 row_count = 0
```

处理：
```
layered_promotion_rates = []
status = normal
```

理由：昨日无涨停股，分母全为 0，无层可输出，结果为空列表，状态正常。

### 11.4 今日合法零涨停

```
昨日有分母（denominator > 0）
今日 limit_up_pool = []
今日 legal_zero = true（适配器确认）
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

### 11.5 未解释空池（previous 或 current）

```
今日 limit_up_pool = []
今日 legal_zero = false
今日 unexplained_empty = true
```

处理（previous 与 current 侧相同）：
```
layered_promotion_rates = null
status = partial
reason_codes = [SOURCE_PARTIAL, UNEXPLAINED_EMPTY]
```

理由：空池无法确认是合法零值还是数据缺失，不能简单视为未晋级。
侧别由对应侧 data_health 标识（`UNEXPLAINED_EMPTY` 的 side 为 previous 或 current），
不包含 `PREVIOUS_SNAPSHOT_UNAVAILABLE` / `CURRENT_SNAPSHOT_UNAVAILABLE`
（这两个 unavailable 侧码仅用于全局失败场景，见第 13.1 节）。

### 11.6 今日普通空池

```
今日 limit_up_pool = []
今日 legal_zero = false
今日 unexplained_empty = false
```

处理：
```
layered_promotion_rates = null
status = unavailable
reason_codes 包含 SOURCE_UNAVAILABLE, CURRENT_SNAPSHOT_UNAVAILABLE
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
| 交易日历不可用 | unavailable | null | TRADING_CALENDAR_UNAVAILABLE, SOURCE_UNAVAILABLE |
| 两侧 trade_date 不匹配 | unavailable | null | TRADE_DATE_MISMATCH, SOURCE_UNAVAILABLE |
| 任一侧非 final | unavailable | null | NOT_FINAL, SOURCE_UNAVAILABLE |
| 昨日合法零涨停 | normal | [] | （无） |
| 今日合法零涨停 | normal | 正常计算（numerator全0, rate=0.0） | （无） |
| 昨日空池未解释 | partial | null | SOURCE_PARTIAL, UNEXPLAINED_EMPTY |
| 今日空池未解释 | partial | null | SOURCE_PARTIAL, UNEXPLAINED_EMPTY |
| coverage_warning=true（任一侧） | partial | null | SOURCE_PARTIAL, PARTIAL_COVERAGE |
| 昨日部分非法行 | partial | null | SOURCE_PARTIAL, INVALID_POOL_ROW, PARTIAL_COVERAGE |
| 今日部分非法行 | partial | null | SOURCE_PARTIAL, INVALID_POOL_ROW, PARTIAL_COVERAGE |
| 昨日池内重复代码 | partial | null | SOURCE_PARTIAL, DUPLICATE_STOCK_CODE, PARTIAL_COVERAGE |
| 今日池内重复代码 | partial | null | SOURCE_PARTIAL, DUPLICATE_STOCK_CODE, PARTIAL_COVERAGE |
| 身份匹配不完整 | partial | null | SOURCE_PARTIAL, IDENTITY_MATCH_INCOMPLETE, PARTIAL_COVERAGE |
| row_count 不匹配 | partial | null | SOURCE_PARTIAL, PARTIAL_COVERAGE |

**统一 partial 语义**：所有 `status=partial` → `layered_promotion_rates=null`。

包括：`SOURCE_PARTIAL`、`PARTIAL_COVERAGE`、`INVALID_POOL_ROW`、
`DUPLICATE_STOCK_CODE`、`IDENTITY_MATCH_INCOMPLETE`、`UNEXPLAINED_EMPTY`、
`row_count mismatch`、`coverage_warning`。

不得保留以下表述：
- partial 状态下仍输出计算结果
- 仅重复代码的 partial 仍输出计算结果
- 部分覆盖后使用合法行继续计算精确比例

理由：任何 partial 都可能使 numerator 或 denominator 不完整。本模块是精确晋级率合同，
不输出可能系统性偏低的近似比例。

**partial 与 unavailable 的 metrics 一致性**：两者均输出 `metrics = null`。
区别在于 `reason_codes`：partial 表示来源部分可用但覆盖不完整，
unavailable 表示来源全局失败或非 final / 日期不匹配。调用方应通过 `reason_codes`
区分降级原因。

**TRADE_DATE_MISMATCH / NOT_FINAL 合同**：该指标要求两个精确 final 交易日，
日期不符或非 final 时不能输出部分比例，必须 `unavailable` + `rates=null`。

### 12.3 双侧 row_count

昨日 `row_count` 与昨日 `limit_up_pool` 原始长度比较；
今日 `row_count` 与今日 `limit_up_pool` 原始长度比较。

## 13. Reason Codes and Status Semantics

### 13.1 完整 reason-code 映射表

| reason_code | trigger | side | status | rates_output | priority | combined_with | notes |
|-------------|---------|------|--------|--------------|----------|---------------|-------|
| `SOURCE_UNAVAILABLE` | 全局来源失败（传输/解析/超时/访问控制） | both | unavailable | null | 1 | 对应侧码 | 全局总括码 |
| `PREVIOUS_SNAPSHOT_UNAVAILABLE` | 昨日快照不可用 | previous | unavailable | null | 2 | SOURCE_UNAVAILABLE | previous 侧原因码 |
| `CURRENT_SNAPSHOT_UNAVAILABLE` | 今日快照不可用 | current | unavailable | null | 3 | SOURCE_UNAVAILABLE | current 侧原因码 |
| `TRADING_CALENDAR_UNAVAILABLE` | 交易日历不可用 | both | unavailable | null | 4 | SOURCE_UNAVAILABLE | 无法确定 previous_trade_date |
| `TRADE_DATE_MISMATCH` | 两侧 trade_date 不匹配 | both | unavailable | null | 5 | SOURCE_UNAVAILABLE | 该指标要求两个精确 final 交易日 |
| `NOT_FINAL` | 任一侧非 final | both | unavailable | null | 6 | SOURCE_UNAVAILABLE | 见第 7.3 节可信 final 合同 |
| `SOURCE_PARTIAL` | 部分可用 | both | partial | null | 7 | 具体部分覆盖码 | partial 总括码 |
| `PARTIAL_COVERAGE` | 部分覆盖（coverage_warning） | both | partial | null | 8 | SOURCE_PARTIAL | 来源无法区分未涨停与未被覆盖 |
| `IDENTITY_MATCH_INCOMPLETE` | 身份匹配不完整 | both | partial | null | 9 | SOURCE_PARTIAL | 跨日匹配存在无法对齐的样本 |
| `INVALID_POOL_ROW` | 池行非法（代码/连板数缺失或非法） | previous/current | partial | null | 10 | SOURCE_PARTIAL | 该行排除 |
| `DUPLICATE_STOCK_CODE` | 池内重复代码 | previous/current | partial | null | 11 | SOURCE_PARTIAL | 保留首次合法记录 |
| `UNEXPLAINED_EMPTY` | 任一侧池为空，legal_zero=false，且无法解释为空 | previous or current，由对应侧 data_health 标识 | partial | null | 12 | SOURCE_PARTIAL | 空池无法确认合法零值；不包含 unavailable 侧码 |

### 13.2 组合规则

```
SOURCE_UNAVAILABLE:
全局总括码

PREVIOUS_SNAPSHOT_UNAVAILABLE:
previous 侧原因码

CURRENT_SNAPSHOT_UNAVAILABLE:
current 侧原因码

一侧全局失败时：
同时输出 SOURCE_UNAVAILABLE + 对应侧码

SOURCE_PARTIAL:
partial 总括码

具体 partial 原因码：
与 SOURCE_PARTIAL 同时输出

partial unexplained empty：
SOURCE_PARTIAL + UNEXPLAINED_EMPTY
（不包含 PREVIOUS_SNAPSHOT_UNAVAILABLE / CURRENT_SNAPSHOT_UNAVAILABLE）
```

### 13.3 优先级排序

```
SOURCE_UNAVAILABLE
PREVIOUS_SNAPSHOT_UNAVAILABLE
CURRENT_SNAPSHOT_UNAVAILABLE
TRADING_CALENDAR_UNAVAILABLE
TRADE_DATE_MISMATCH
NOT_FINAL
SOURCE_PARTIAL
PARTIAL_COVERAGE
IDENTITY_MATCH_INCOMPLETE
INVALID_POOL_ROW
DUPLICATE_STOCK_CODE
UNEXPLAINED_EMPTY
```

### 13.4 状态规则

```
normal:
  reason_codes = []
  warnings = []
  metrics = 正常计算（含空列表 [] 表示昨日合法零涨停）

partial:
  reason_codes 至少包含 SOURCE_PARTIAL + 具体部分覆盖码
  warnings = ["snapshot partially available; rates suppressed due to coverage_warning"]
  metrics = null

unavailable:
  reason_codes 至少包含 SOURCE_UNAVAILABLE（或 TRADE_DATE_MISMATCH / NOT_FINAL / TRADING_CALENDAR_UNAVAILABLE）+ 对应侧码
  warnings = ["snapshot unavailable; no layered promotion rates emitted"]
  metrics = null
```

### 13.5 rates 输出规则汇总

```
unavailable → rates=null
partial → rates=null
previous legal zero → rates=[]
current legal zero → concrete zero-rate array（每层 rate=0.0）
normal → reason_codes=[]，rates 正常计算
```

## 14. Controlled Probe Results

```
probes_performed_by_Q = 0
```

本轮未执行实时网络探针。详见第 4.3 节 reviewer-provided evidence。

仓库使用层面已确认：
- `em_zt_topic_pool` 传递 `date` 参数
- `getTopicZTPool` 端点用于当日/历史涨停池
- `getYesterdayZTPool` 端点用于昨涨停池
- 池内字段 `c`（代码）和 `lbc`（连板数）被仓库读取

上游语义层面尚未确认：
- `getTopicZTPool` 历史日期可用性：partially_verified（reviewer-provided，Q 未复验）
- `getYesterdayZTPool` 与指定前一交易日池的关系：not_verified
- `lbc` 首板/连板及跨日晋级语义：not_verified
- 空数组语义：not_verified
- final 稳定状态：not_verified
- source update time：not_verified

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
不使用 `9/4/8/920` 前缀作为正常样本。前缀合同用于市场板块形状校验，
**不用于排除 ST/*ST**。ST/*ST 使用相同的市场代码前缀。

`identity_edge` case 中的前导零、重复、非法代码场景由 `edge_case_notes` 说明，
实际池行仍使用合法前缀以保持校验一致性。`identity_edge` 是 normal case，
其实际池不得包含重复或非法行；重复、非法只可作为合同说明，不得声称该 normal case
实际执行了这些 partial 情形。

## 16. Risks and Licensing Boundary

### 16.1 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 交易日历不完整（节假日） | 高 | 必须先实现交易日历接口 |
| 东财端点反爬 | 中 | 控制请求频率，复用现有缓存机制 |
| 跨日身份匹配不完整 | 中 | 标记 PARTIAL_COVERAGE，不假设缺失=未晋级 |
| final 判定不准 | 中 | 需实现可信 final 生产者，不依赖调用方声明 |
| 停牌股无法区分 | 低 | 标记 PARTIAL_COVERAGE，若有独立停牌源可升级 |

### 16.2 许可边界

- 东财 push2ex 端点为公开行情接口，现有项目已使用
- 不提交原始完整响应
- 不提交 Cookie、Token、URL 参数中的敏感值
- 不绕过验证码或访问控制
- 不提高并发（请求间隔 >= 1.2 秒）
- 不持续轮询

## 17. Implementation Entry Conditions

```
implementation_allowed: false
```

### 17.1 完整阻断条件清单（九项）

以下九项必须全部闭合后才允许进入 `layered_promotion_rates` 生产实现。
Executive Decision、本节、第 18.2 节使用同一份清单。

#### 1. 交易日历的唯一来源、许可、覆盖年份、更新机制和接口尚未实现

- risk: 节假日后首个交易日使用错误的昨日快照，产出错误的晋级率
- closure action: 选择唯一交易日历源，实现 `previous_trade_date`，记录第 5.4 节字段
- acceptance evidence: 抽象测试通过（长假后首日、周末输入、非交易日输入、未来日期、超出覆盖年份）

#### 2. 至少 3 组相邻交易日的股票身份与 lbc 跨日关系尚未机械验证

- risk: `lbc` 跨日晋级语义未验证，numerator 可能系统性错误
- closure action: 执行第 4.3 节受控探针，覆盖 3 组相邻交易日（含节假日边界）
- acceptance evidence: 3 组探针结果记录、跨日身份匹配一致、lbc 满足 N→N+1 关系

#### 3. getTopicZTPool 历史日期语义仍仅 partially_verified

- risk: 历史日期返回的池可能不是 final 稳定快照
- closure action: 补充受控探针，验证历史日期返回的池为 final 稳定
- acceptance evidence: 探针结果记录、final 稳定性确认

#### 4. getYesterdayZTPool 与指定前一交易日池的关系仍为 not_verified

- risk: 本合同不使用 `getYesterdayZTPool`，但若未来考虑使用，需验证其语义
- closure action: 若不使用则标记为不采用；若使用则验证与 `getTopicZTPool(previous_date)` 一致
- acceptance evidence: 决策记录或探针结果

#### 5. previous/current 可信 final 快照生产者和稳定窗口尚不存在

- risk: 调用方传入 `session="final"` 只是声明，不能证明来源快照已 final
- closure action: 实现 final 快照生产者，含 trade_date 校验、字段完整性、稳定窗口、失败和超时语义
- acceptance evidence: 生产者实现、稳定窗口判定逻辑、失败降级测试

#### 6. 来源适配器尚不能区分 legal zero、非交易日、传输失败、解析失败、限流和访问控制

- risk: 空数组被误判为合法零涨停，产出错误的 `rates=[]`
- closure action: 实现适配器，输出第 11.2 节十字段
- acceptance evidence: 适配器实现、各失败场景测试、legal_zero 仅在适配器确认时为 true

#### 7. ST/*ST、BSE 等 universe 必须与 Slice 0 权威合同一致

- risk: universe 偏离导致 denominator 计算错误
- closure action: 以 Slice 0 可行性文档 universe 表为权威，ST/*ST included，BSE excluded
- acceptance evidence: universe 合同一致、代码校验通过

#### 8. partial 覆盖时 rates=null 的保守合同必须完整落地

- risk: partial 强行计算产出系统性偏低的近似比例
- closure action: 落地第 12.2 节统一 partial 语义，所有 partial → rates=null
- acceptance evidence: 测试覆盖所有 partial reason-code、rates 均为 null

#### 9. fixture、reason-code 和状态映射必须通过机械验证

- risk: 合同内部不一致
- closure action: 执行第 15 节 fixture 校验、第 16 节文档扫描
- acceptance evidence: JSON 校验通过、合同校验脚本通过、文档扫描无命中

### 17.2 检查清单

```
[ ] 1. 交易日历实现
[ ] 2. 3 组相邻交易日跨日验证
[ ] 3. getTopicZTPool 历史日期语义验证
[ ] 4. getYesterdayZTPool 关系验证（或不采用决策）
[ ] 5. final 快照生产者及稳定窗口明确
[ ] 6. 来源适配器区分 legal zero / 失败
[ ] 7. universe 与 Slice 0 一致
[ ] 8. partial rates=null 落地
[ ] 9. fixture / reason-code / 状态映射机械验证
```

不得保留：
```
[x] final 判定路径明确：依赖调用方传入 session="final"
```

### 17.3 前置依赖

- **必须先实现** `backend/trade_calendar.py` 的 `previous_trade_date` 函数
- **必须先实现** final 快照生产者
- **必须先实现** 来源适配器（含 legal_zero 区分）
- 建议在下一独立子阶段实现

## 18. GO / CONDITIONAL GO / NO-GO Decision

### 18.1 决策

```
overall: CONDITIONAL GO
implementation_allowed: false
```

### 18.2 完整阻断条件清单（九项）

与第 1 节 Executive Decision、第 17.1 节使用同一份清单。

```
1. 交易日历的唯一来源、许可、覆盖年份、更新机制和接口尚未实现
2. 至少 3 组相邻交易日的股票身份与 lbc 跨日关系尚未机械验证
3. getTopicZTPool 历史日期语义仍仅 partially_verified
4. getYesterdayZTPool 与指定前一交易日池的关系仍为 not_verified
5. previous/current 可信 final 快照生产者和稳定窗口尚不存在
6. 来源适配器尚不能区分 legal zero、非交易日、传输失败、解析失败、限流和访问控制
7. ST/*ST、BSE 等 universe 必须与 Slice 0 权威合同一致
8. partial 覆盖时 rates=null 的保守合同必须完整落地
9. fixture、reason-code 和状态映射必须通过机械验证
```

每项的 risk、closure action、acceptance evidence 见第 17.1 节。

### 18.3 内部一致性

- 计算公式合同已经可以定义
- 来源、日历、final、适配器和跨日验证尚未闭合
- 当前不得进入 `layered_promotion_rates` 生产实现
- 不得在某一章节勾选已满足，而在另一章节又列为未满足

### 18.4 关闭后流程

九项全部闭合后，重新评估进入生产实现的条件。不得仅关闭其中一项即直接生产。
