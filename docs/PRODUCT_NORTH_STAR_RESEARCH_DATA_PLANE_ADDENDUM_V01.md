# Vibe-Research North Star Addendum — Research Data Plane v0.1

> 状态：**PRODUCT_DIRECTION_FROZEN_ADDENDUM_V0.1**
>
> 日期：2026-08-12
>
> Authority：本文件是 `docs/PRODUCT_NORTH_STAR_V01.md` 的正式补充，补充其 **§13 数据路线** 与 **§30 Data Governance Foundation**。若本文件与旧文档中关于本地研究行情运行层的未冻结描述冲突，以本 Addendum 为准。
>
> 治理边界：本文件冻结产品/架构方向，**不是代码实施授权**。具体 PoC、生产接入、依赖增加、PR Ready / Merge 仍以 `docs/NEXT_TASK.md` 与用户后续明确授权为准。

---

## 1. 为什么需要独立 Research Data Plane

Vibe-Research 的长期数据体系不能把“事实是否可信”与“历史数据是否能高性能查询”混成一个问题。

随着产品进入全 A 股扫描、长历史窗口、分钟线/tick、指标计算、历史回放和回测，单纯依赖：

`Provider → HTTP → Python → DataFrame → 即时计算`

会逐渐成为性能、重复下载和工程复杂度瓶颈。

因此 North Star 正式增加一个独立能力层：

> **Research Data Plane / Noncanonical Local Market Data Runtime**

它负责大规模历史市场数据的本地读取与计算效率；它**不负责定义正式投资事实的真值**。

---

## 2. 双轨数据架构

### 2.1 Canonical Fact Plane — 负责“真”

Canonical Fact Plane 继续承担正式事实权威：

- Raw Observation / Normalized Fact
- Temporal Semantics / PIT
- Source Provenance
- Revision / Restatement
- Data Health
- Cross-source Reconciliation
- Canonical Admissibility

标准链路仍为：

`Provider → Raw Observation → Normalization → Canonical Fact → Temporal Semantics → Provenance → Data Health → Reconciliation → Evidence / Thesis / Decision`

Formal Decision、Hard Risk、Material Change 以及其它 authoritative surface 所依赖的事实，不因本 Addendum 而改变其既有权威链。

### 2.2 Research Data Plane — 负责“快”和“大规模计算”

Research Data Plane 面向：

- Historical OHLCV
- 分钟线 / tick
- 全市场批量查询
- 技术指标计算
- Screening / Discovery
- Historical Replay
- Backtest
- Local Cache / Mirror
- 大规模横截面与时序研究

它可以使用面向查询性能优化的本地存储或运行时实现，但其结果默认属于：

> **Research Observation / Analytical Input**

而不是 Canonical Fact。

---

## 3. Authority Constitution

以下规则冻结为 North Star 级硬边界：

### 3.1 Research Runtime ≠ Canonical Fact Authority

`Research Runtime` 的本地存在、查询成功、checksum 正确或镜像文件完整，均不能自动证明数据具有正式事实权威。

**文件完整性证明 ≠ 来源真实性 / provenance 证明。**

### 3.2 Research Observation 不得自动升级为 Formal Fact

Research Data Plane 产生的行情值、指标、信号、筛选结果、回测结果或其它 observation，不得仅因“已经存在于本地数据库”而自动进入：

- Canonical Fact
- Formal Thesis
- Formal Decision
- Hard Risk CONFIRMED
- Material Change MATERIAL / CRITICAL
- Historical Instrument Universe authority

### 3.3 正式使用必须经过既有权威链

当 Research Data Plane 中的某个 observation 需要进入正式决策语义时，必须经过与其 claim 类型相匹配的既有事实治理链，例如：

`Research Observation → Source / Temporal / Provenance Validation → Data Health / Reconciliation → Canonical Fact / Canonical Evidence`

具体是否需要全部步骤，由对应 Dataset / Claim contract 决定；不得由 Research Runtime 自行授予 canonical authority。

### 3.4 Research Runtime 不得绕过 PIT / 时间语义

尤其禁止：

- local latest 冒充 historical PIT
- retrieval time 冒充 market fact time
- local vintage 冒充 provider revision
- 当前股票池反推历史股票池
- 未知复权口径拼接为已知口径

已有语义宪法继续成立：

- `Provider Response ≠ Canonical Fact`
- `by_date ≠ PIT`
- `retrieval time ≠ market fact time`
- `local vintage ≠ provider revision`

---

## 4. 允许用途

Research Data Plane 可以优先用于：

- 历史 OHLCV 高性能查询
- 分钟线 / tick 研究
- 技术指标批量计算
- 全市场低成本初筛
- P2 Discovery 的计算型前置筛选
- 策略研究与回测
- 决策时间点历史回放的非权威计算辅助
- 本地缓存与重复查询加速
- 与 canonical provider 的 secondary reconciliation observation

其中 Screening / Backtest / Indicator 等输出属于研究层；它们本身无权产生 BUY / SELL 或 Formal Decision。

---

## 5. 禁止作为唯一权威的用途

Research Data Plane 不得单独作为以下事实的唯一 authority：

- Canonical market facts
- 唯一涨停 / 跌停事实源
- 唯一证券历史 Universe
- Listing / Delisting authoritative state
- PIT 财务事实
- Formal Decision facts
- Hard Risk confirmation
- Material Change confirmation
- 正式 Outcome 的历史价格真值（除非该 Dataset 已通过独立 canonical promotion contract）

不得因 Research Runtime 性能更好而静默替换现有已批准 Provider / Fact Lake authority。

---

## 6. 与 Local Research Fact Lake 的关系

`Local Research Fact Lake` 与 `Research Data Plane` 是相邻但不同的职责：

### Local Research Fact Lake

目标：

> **可复查、可重放、可冻结的正式研究事实基础。**

重点是：

- PIT
- provenance
- revision
- immutable observation
- canonical admissibility
- as_of query

### Research Data Plane

目标：

> **大规模历史市场数据的低延迟本地查询与计算。**

重点是：

- throughput
- batch query
- minute / tick workloads
- indicators
- replay
- backtest
- cache

两者可以共享底层文件或查询技术，但**authority contract 必须保持独立**，不得因为物理存储相同而合并语义层。

---

## 7. 与实时监控的边界

本能力不改变现有 Deferred / Non-goal：

> **全市场分钟级实时监控仍不是当前产品目标。**

“本地分钟线 / tick 历史研究”与“后台实时分钟级监控”是两个不同能力。

本 Addendum 不授权：

- Scheduler
- Background Agent
- 24/7 monitoring
- 实时交易执行
- 券商连接

---

## 8. 第三方实现与技术选型原则

North Star 冻结的是：

> **Research Data Plane 这个长期能力与 authority boundary。**

North Star **不冻结任何具体第三方项目为永久依赖**。

任何第三方本地行情数据库 / runtime 都只是可替换实现候选，必须经过独立 PoC 后才能进入工程决策。

因此：

`Capability is frozen; implementation is replaceable.`

---

## 9. free-stockdb 当前定位

`hello245m/free-stockdb` 当前只作为：

> **Noncanonical Local Market Data Runtime PoC / architecture candidate**

可重点验证：

- Historical OHLCV
- 分钟线 / tick
- 本地批量查询
- 指标计算
- 全市场扫描
- Replay / Backtest
- Local cache / mirror
- 查询吞吐与资源成本

但当前不得把其 mirror 数据直接升级为：

- canonical fact source
- PIT authority
- historical universe authority
- 唯一涨停事实源
- Hard Risk / Material Change authority

其 manifest / checksum / mirror 完整性只能证明对应文件传输与本地内容一致性，不能替代上游数据生产者、发布时间、修订语义和 provenance 的验证。

该定位不代表 production dependency 已获批准。

---

## 10. Future PoC Gate

任何候选 Research Runtime 在真正接入前，至少应独立验证：

1. **Adjustment semantics**：不复权 / 前复权 / 后复权口径是否明确且稳定。
2. **Temporal semantics**：交易日、分钟/tick 时间、时区、停牌、集合竞价等语义。
3. **Security lifecycle**：上市、退市、代码变化、历史股票池处理。
4. **Missing-data semantics**：缺失、0、空值、跳过、unavailable 是否可区分。
5. **Dataset version / update semantics**：同步后如何识别数据发生变化。
6. **Cross-source reconciliation**：抽样与已批准 canonical/verifier provider 对比 OHLCV。
7. **Reproducibility**：同 dataset/version 的相同查询是否可重复。
8. **Performance value**：全市场 × 长历史 × 分钟级 workload 相对现有链路的实际收益。

PoC 失败不得通过降低 canonical contract 来“适配”第三方实现。

---

## 11. Roadmap / Priority Boundary

Research Data Plane 是长期 North Star 能力，但**不因发现某个优秀开源项目而自动抢占 Capital-First P0 主线**。

当前真实持仓决策闭环的优先级仍高于 Research Runtime 工程优化。

因此本 Addendum：

- 不改变当前 Decision Inbox / Risk / Evidence 主线的实施优先级；
- 不自动授权 free-stockdb PoC；
- 不自动增加 production dependency；
- 不修改现有 canonical provider routing；
- 不允许以“工程体验提升”为理由绕过 Data Governance。

只有当对应 slice 被写入 `docs/NEXT_TASK.md` 并获得明确授权后，才进入实施。

---

## 12. Frozen Summary

```text
RESEARCH_DATA_PLANE = REQUIRED_LONG_TERM_CAPABILITY

PRIMARY_ROLE =
  SPEED_AND_SCALE

CANONICAL_FACT_AUTHORITY =
  NO

DEFAULT_OUTPUT_CLASS =
  RESEARCH_OBSERVATION

PRIMARY_WORKLOADS =
  HISTORICAL_OHLCV
  MINUTE_TICK
  BULK_SCAN
  INDICATORS
  REPLAY
  BACKTEST
  LOCAL_CACHE

FORMAL_PROMOTION =
  THROUGH_EXISTING_FACT_PROVENANCE_HEALTH_RECONCILIATION_AUTHORITY

THIRD_PARTY_IMPLEMENTATION =
  REPLACEABLE

FREE_STOCKDB =
  POC_CANDIDATE_ONLY

P0_PRIORITY_CHANGED =
  NO

IMPLEMENTATION_AUTHORIZED =
  NO
```
