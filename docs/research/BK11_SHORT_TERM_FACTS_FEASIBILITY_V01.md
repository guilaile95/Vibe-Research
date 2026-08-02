# BK-11 Slice 0：短线市场事实数据与口径可行性审计

| 项 | 值 |
|----|-----|
| 分支 | `research/bk11-short-term-facts-feasibility-v0.1` |
| Base | `463dd6b6c375e20003fe07af73ae2faf69136ee3` |
| 状态 | Slice 0 审计交付 |
| 范围 | 仅审计，不实现产品页面 |

---

## 1. 来源 Tier 分级

### Tier A：主源（零鉴权、已实测、项目内已有调用路径）

| 来源 | 端点 | 覆盖 | 项目内现状 |
|------|------|------|-----------|
| 东财涨停板四池 (push2ex) | `getTopicZTPool` / `getTopicZBPool` / `getTopicDTPool` / `getYesterdayZTPool` | 涨停/炸板/跌停/昨涨停今表现 | `astock.em_zt_topic_pool()` 已实现；`market._emotion()` 已调用 |
| 东财全 A 快照 (push2) | `a_share_snapshot()` 分页 | 涨跌家数/涨跌幅/成交额/换手率 | `astock.a_share_snapshot()` + `market.calculate_market_breadth()` 已实现 |

### Tier B：增强源（零鉴权、实测可用、项目内未接入）

| 来源 | 端点 | 覆盖 | 接入成本 |
|------|------|------|---------|
| 同花顺涨停揭秘 (10jqka) | `ths_limit_up_pool(date)` | 涨停原因题材/封板成功率/板型 | 低：单函数，a-stock-data SKILL 已有完整代码 |
| 东财行业板块排名 (push2) | `board_ranking("industry")` | 行业涨跌/上涨下跌家数 | 已实现：`astock.board_ranking()` |

### Tier C：备选源（可用但有限制）

| 来源 | 限制 | 降级场景 |
|------|------|---------|
| 腾讯财经 (qt.gtimg.cn) | 无涨停板池能力；仅个股行情 | 涨停池不可用时不提供短线结构指标 |
| 通达信 (mootdx TCP 7709) | 无涨停板池；仅 K 线/财务 | 不作为短线事实源 |

### 分级结论

Slice 1–2 的全部核心指标可由 **Tier A 单独覆盖**。Tier B 仅增强题材归因，不构成硬依赖。Tier C 不参与短线事实层。

---

## 2. 市场范围合同

```text
覆盖范围：沪深 A 股主板 + 中小板 + 创业板 + 科创板
排除范围：北交所（8 开头）、ST 退市整理期、新股上市首日（无涨跌幅限制日）
涨停判定：涨幅 >= 对应板块涨跌幅限制（主板 10%、创业板/科创板 20%）
数据来源判定：东财涨停板池已按交易所规则过滤，项目不自行计算涨停价
```

**已知边界**：

- 东财池不含北交所（8 开头），与项目 `astock.get_prefix()` 的 `bj` 前缀一致排除。
- ST 股涨跌幅 5%，东财池按实际涨停价入池，无需项目额外处理。
- 注册制新股前 5 日无涨跌幅限制，不会出现在涨停池中。

---

## 3. 交易日与场次语义

### 3.1 交易日判定

```text
东财涨停板池 date 参数必须为交易日（YYYYMMDD）。
非交易日/节假日：data 字段返回 null，pool 为空列表。
项目现有逻辑：market._emotion() 从今天往前回溯 8 天，取第一个有涨停池的日期。
```

### 3.2 场次语义

| 时段 | 数据状态 | 语义 |
|------|---------|------|
| 盘前（< 09:25 CST） | 上一交易日收盘数据 | `data_trade_date` = 上一交易日 |
| 集合竞价（09:25–09:30） | 当日数据开始更新但不完整 | status = partial |
| 盘中（09:30–15:00） | 当日实时数据，涨停池动态变化 | status = normal（覆盖率达标时） |
| 收盘后（>= 15:00） | 当日最终数据 | status = normal |
| 非交易日 | 上一交易日数据 | `data_trade_date` = 最近交易日 |

### 3.3 合同约束

```text
每条事实记录必须携带 data_trade_date（YYYY-MM-DD）。
不得把盘中动态数据标记为 final。
Preflight 检查必须验证 data_trade_date 与当前请求日期的关系。
```

---

## 4. 核心指标字段合同

### 4.1 市场宽度（Slice 1）

| 字段 | 类型 | 来源 | 计算方式 |
|------|------|------|---------|
| `up_count` | int | 全 A 快照 | change_pct > 0 的股票数 |
| `down_count` | int | 全 A 快照 | change_pct < 0 的股票数 |
| `flat_count` | int | 全 A 快照 | change_pct == 0 的股票数 |
| `up_ratio` | float [0,1] | 纯计算 | up_count / valid_count |
| `zt_count` | int | 涨停池 | len(zt_pool) |
| `dt_count` | int | 跌停池 | len(dt_pool) |
| `zb_count` | int | 炸板池 | len(zb_pool) |
| `break_rate` | float [0,1] \| null | 纯计算 | zb_count / (zt_count + zb_count) |
| `seal_rate` | float [0,1] \| null | 纯计算 | zt_count / (zt_count + zb_count) |

### 4.2 短线结构（Slice 2）

| 字段 | 类型 | 来源 | 计算方式 |
|------|------|------|---------|
| `max_boards` | int | 涨停池 | max(limit_days) |
| `lianban_count` | int | 涨停池 | count(limit_days >= 2) |
| `ladder` | list[{boards, count}] | 涨停池 | 按连板数分档计数 |
| `promotion_rate` | float [0,1] \| null | 涨停池 + 昨涨停池 | lianban_count / yzt_count |
| `yzt_count` | int | 昨涨停池 | len(yzt_pool) |
| `lianban_premium` | float \| null | 昨涨停池 | mean(yzt_pool.pct) |
| `loss_effect` | float \| null | 昨涨停池 | count(pct < 0) / yzt_count |

### 4.3 通用元数据字段

```text
source_id: str          — 数据源标识（如 "eastmoney_limit_pool"）
data_trade_date: str    — YYYY-MM-DD
observed_at: str        — ISO 8601 UTC
status: str             — normal / partial / unavailable
is_stale: bool          — 数据是否过期
warnings: list[str]     — 降级原因
```

---

## 5. 三交易日跨来源验证

以 2026-07-28 / 2026-07-29 / 2026-07-30 三个连续交易日为审计样本。下表数值为东财 push2ex 实测值，与 C 复审提供的基准值逐日比对一致。

### 5.1 验证矩阵

| 指标 | 07-28 | 07-29 | 07-30 | 跨源一致性 |
|------|-------|-------|-------|-----------|
| zt_count（涨停池） | 61 | 81 | 52 | 东财池与同花顺涨停揭秘数量偏差 < 5%（同花顺含 ST，07-28 实测 THS=60 vs EM=61） |
| zb_count（炸板池） | 20 | 14 | 19 | 单源（东财），无交叉验证 |
| dt_count（跌停池） | 49 | 9 | 74 | 单源（东财） |
| up_count（广度） | > 0 | > 0 | > 0 | 全 A 快照 valid_count > 4500 |
| break_rate | [0,1] | [0,1] | [0,1] | 纯计算，无跨源问题 |
| promotion_rate | [0,1] | [0,1] | [0,1] | 依赖 yzt_count > 0 |
| ladder（连板梯队） | 非空 | 非空 | 非空 | 单源 |

### 5.2 C 复审基准值比对

| 日期 | 指标 | C 复审值 | 东财实测值 | 一致性 |
|------|------|---------|-----------|--------|
| 2026-07-28 | zt | 61 | 61 | ✓ |
| 2026-07-28 | zb | 20 | 20 | ✓ |
| 2026-07-28 | dt | 49 | 49 | ✓ |
| 2026-07-29 | zt | 81 | 81 | ✓ |
| 2026-07-29 | zb | 14 | 14 | ✓ |
| 2026-07-29 | dt | 9 | 9 | ✓ |
| 2026-07-30 | zt | 52 | 52 | ✓ |
| 2026-07-30 | zb | 19 | 19 | ✓ |
| 2026-07-30 | dt | 74 | 74 | ✓ |

### 5.3 验证结论

```text
涨停/炸板/跌停/昨涨停：单源（东财 push2ex），C 复审三日基准值与东财实测值逐日一致。
市场广度（涨跌家数）：单源（东财 push2 全 A 快照），腾讯行情可验证个股涨跌幅但不提供全市场统计。
同花顺涨停揭秘：作为题材归因增强源，07-28 实测 THS=60 vs EM=61（偏差 1，THS 含 ST 口径差异），不作为涨停数硬交叉源。
风险：东财 push2ex 间歇风控（HTTP 000 / 空响应），已有 em_get() 限流缓解。
缓解：Data Health 标记 unavailable + Preflight 阻断，不伪造数据。
```

---

## 6. 许可和展示边界

### 6.1 数据许可

| 来源 | 许可 | 限制 |
|------|------|------|
| 东财 push2/push2ex | 公开行情接口，无 API Key | 不得商用再分发；个人研究用途 |
| 同花顺 10jqka | 公开页面数据 | 不得高频抓取；展示需标注来源 |
| 腾讯 qt.gtimg.cn | 公开行情 | 不封 IP，无明确 ToS |

### 6.2 展示边界

```text
所有短线事实指标仅用于个人复盘研究。
前端展示必须标注数据来源和 data_trade_date。
不得展示为"投资建议"或"买卖信号"。
AI 叙述（Slice 5）不得重新计算核心数字，只能引用已提交快照。
```

---

## 7. 缓存策略

### 7.1 现有策略（market.py）

```text
TTL = 300 秒（5 分钟）
粒度 = 全站共享单份缓存
空结果不缓存（下次请求重试）
键 = 函数级字符串（"emotion" / "a_share_snapshot"）
```

### 7.2 BK-11 建议策略

```text
缓存键 = source_id + data_trade_date
盘中 TTL = 300 秒（与现有一致）
收盘后 TTL = 无限（当日数据不再变化）
非交易日 = 返回最近交易日缓存
持久化 = 不持久化（内存缓存，重启后重新拉取）
```

### 7.3 约束

```text
不得把不同 data_trade_date 的数据混合计算。
缓存失效时必须重新拉取，不得用过期数据填充。
```

---

## 8. Data Health 映射

### 8.1 新增 source_id

| source_id | module | display_name | stale_after_seconds |
|-----------|--------|-------------|-------------------|
| `eastmoney_limit_pool` | market | 东财涨停板池 | 600 |
| `eastmoney_market_breadth` | market | 东财全A市场广度 | 600 |

### 8.2 状态映射

| 条件 | status | error_code |
|------|--------|-----------|
| 涨停池 + 广度均正常且覆盖率达标 | normal | — |
| 涨停池正常但广度覆盖率不足 | partial | SOURCE_PARTIAL |
| 广度正常但涨停池为空（非交易日除外） | partial | SOURCE_PARTIAL |
| 涨停池请求失败（HTTP 000 / 超时） | unavailable | SOURCE_UNAVAILABLE |
| 全 A 快照为空 | unavailable | MARKET_BREADTH_UNAVAILABLE |
| 数据超过 stale_after_seconds | partial | SOURCE_STALE |

### 8.3 与现有 Adapter 的关系

```text
复用 data_health_adapters.py 的 AdapterReadError 机制。
新增 Adapter 只读、不联网、不写文件。
blocks_advice = True 当 status == unavailable。
```

---

## 9. Preflight 充分性规则

### 9.1 规则定义

Preflight 在每次事实计算前执行，验证输入数据是否满足最小充分性：

| 规则 ID | 条件 | 不满足时 |
|---------|------|---------|
| PF-01 | data_trade_date 为有效交易日 | status = unavailable |
| PF-02 | 全 A 快照 valid_count >= 4000 | status = partial, warning |
| PF-03 | 涨停池非空（交易日盘中/收盘后） | status = partial, warning |
| PF-04 | 涨停池 + 炸板池至少一个非空 | break_rate = null |
| PF-05 | 昨涨停池非空（计算晋级率时） | promotion_rate = null |
| PF-06 | observed_at 与当前时间差 < stale_after_seconds | is_stale = True |

### 9.2 降级语义

```text
normal：PF-01 ~ PF-03 全部满足
partial：PF-01 满足但 PF-02 或 PF-03 不满足
unavailable：PF-01 不满足，或数据源完全不可达
```

---

## 10. 离线 Fixture 合同

配套文件：`docs/research/BK11_SHORT_TERM_FACTS_FIXTURE_V01.json`

### 10.1 结构

```json
{
  "schema_version": "bk11-short-term-facts-fixture.v0.1",
  "fixture_kind": "synthetic-normalized",
  "generated_at": "<ISO 8601 UTC>",
  "trade_dates": ["<YYYY-MM-DD>", ...],
  "cases": [
    {"case_id": "normal", "case_name": "...", ...},
    {"case_id": "partial", "case_name": "...", ...},
    {"case_id": "unavailable", "case_name": "...", ...}
  ]
}
```

### 10.2 用途

```text
Slice 1+ 的单元测试使用 fixture 中 cases 数组的 normal/partial/unavailable 场景。
不依赖网络即可验证指标计算、降级逻辑、Preflight 规则。
fixture 中的数字为手动构造的合成值，仅用于测试 schema 和计算一致性，
不代表实际历史市场数据。
```

---

## 11. 逐指标决策

| 指标 | 来源充分性 | 口径明确性 | 跨源验证 | 决策 |
|------|-----------|-----------|---------|------|
| up_count / down_count / flat_count | ✓ 全 A 快照已实现 | ✓ 纯计算 | 单源 | **GO** |
| up_ratio | ✓ | ✓ | 纯计算 | **GO** |
| zt_count | ✓ 涨停池已实现 | ✓ len(pool) | 单源 | **GO** |
| dt_count | ✓ 跌停池已实现 | ✓ len(pool) | 单源 | **GO** |
| zb_count | ✓ 炸板池已实现 | ✓ len(pool) | 单源 | **GO** |
| break_rate / seal_rate | ✓ | ✓ 纯计算 | 纯计算 | **GO** |
| max_boards / lianban_count / ladder | ✓ 涨停池 limit_days | ✓ | 单源 | **GO** |
| promotion_rate | ✓ 需昨涨停池 | ✓ 分子/分母明确 | 单源 | **GO** |
| lianban_premium（连板溢价） | ✓ 昨涨停池 pct | ✓ mean(pct) | 单源 | **CONDITIONAL GO** |
| loss_effect（亏钱效应） | ✓ 昨涨停池 pct < 0 | ✓ 比例 | 单源 | **CONDITIONAL GO** |
| 题材结构 | △ 需同花顺增强 | △ 归因口径不统一 | 无 | **CONDITIONAL GO** |

### CONDITIONAL GO 条件

```text
lianban_premium：昨涨停池 yzt_count >= 5 时计算，否则 null。
loss_effect：同上。
题材结构：Slice 2 不硬依赖同花顺；若同花顺不可用则题材字段为 null，不阻断其他指标。
```

---

## 12. 整体 Slice 0 决策

### **CONDITIONAL GO**

理由：

1. 全部 Slice 1 核心指标（市场宽度 + 涨跌停 + 炸板率 + 封板率）的数据源已在项目内实现并稳定运行。
2. Slice 2 结构指标（连板梯队/晋级率）的数据源（昨涨停池）已在 `market._emotion()` 中调用。
3. Data Health / Preflight / 缓存策略可复用现有架构，无需新建基础设施。
4. 无许可风险（个人研究用途，公开接口）。
5. 无硬阻塞依赖（BK-07 Provider 抽象为可选增强）。
6. C 复审三日基准值（2026-07-28/29/30）与东财实测值逐日一致（见 §5.2）。

### GO 条件

```text
1. 涨停/炸板/跌停池为单源（东财 push2ex），无独立第二源交叉验证。
   进入 Slice 1 后，T+1 人工复盘验证（Slice 4）作为唯一数据质量后置校验。
2. 东财 push2ex 间歇风控（HTTP 000 / 空响应），必须通过 Data Health 标记
   unavailable + Preflight 阻断，不伪造数据。
3. 同花顺涨停揭秘仅作题材归因增强源，不作为涨停数硬交叉源（含 ST 口径差异）。
4. lianban_premium / loss_effect / 题材结构为 CONDITIONAL GO，依赖昨涨停池
   yzt_count >= 5，否则置 null。
```

风险与缓解：

| 风险 | 影响 | 缓解 |
|------|------|------|
| 东财 push2ex 间歇风控 | 涨停池暂时不可用 | Data Health unavailable + 不伪造 |
| 单源无交叉验证 | 数据错误无法自动发现 | T+1 人工复盘验证（Slice 4） |
| 盘中数据动态变化 | 快照不一致 | 统一 data_trade_date + observed_at |

---

## 13. Slice 1 进入条件

```text
1. 本 Slice 0 审计文档已提交并推送。
2. 用户明确授权进入 Slice 1。
3. Slice 1 范围：市场宽度 + 涨跌停事实（up_count, down_count, zt_count, dt_count, zb_count, break_rate, seal_rate）。
4. Slice 1 必须：纯计算、无 LLM、统一 envelope、接入 Data Health、固定 fixture 测试。
5. Slice 1 不得：新建前端页面、修改 router/app、引入新依赖。
```

---

## 附录 A：现有代码路径

| 能力 | 文件 | 函数 |
|------|------|------|
| 涨停板四池原始请求 | `backend/astock.py` | `em_zt_topic_pool()` |
| 短线情绪计算 | `backend/market.py` | `_emotion()` |
| 市场广度纯计算 | `backend/market.py` | `calculate_market_breadth()` |
| 市场广度状态信封 | `backend/market.py` | `get_market_breadth()` |
| Data Health Adapter 基类 | `backend/data_health_adapters.py` | `AdapterReadError` |
| Data Health 服务 | `backend/data_health_service.py` | — |

## 附录 B：不处理事项

```text
AlertEvaluation 自约束
嵌套 dict 自动模型化
跨字段 technical_status/metrics 一致性
API router 实现
前端页面
通知/调度
求值历史
数据库迁移
LangGraph / 多 Agent
vibe-astock 仓库代码复制
```
