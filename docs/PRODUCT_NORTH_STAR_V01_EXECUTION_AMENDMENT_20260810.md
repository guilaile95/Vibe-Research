# North Star Execution Amendment — Data Governance Foundation

> 状态：**USER_AUTHORIZED_EXECUTION_CORRECTION**
> 日期：2026-08-10
> 适用文档：`docs/PRODUCT_NORTH_STAR_V01.md`
> 适用范围：仅修正 Section 30.5 / 30.6 / 30.7.3 中对 Data Governance Foundation 的**执行顺序与依赖关系**理解；其它 North Star 产品方向与不变量保持不变。
>
> 本修正案保留原 North Star 的历史记录，不把 executor 排程误写成产品不变量。若本修正案与 Section 30.5 / 30.6 / 30.7.3 的串行表述冲突，**以本修正案为当前执行权威**。具体当前授权仍同步记录于 `docs/NEXT_TASK.md`。

---

## 1. 审查结论

原 Section 30 的总体方向正确：

`Provider → Raw Observation → Normalization → Canonical Fact → Temporal Semantics → Provenance → Data Health → Cross-source Reconciliation → Evidence / Thesis / Decision`

但原来的：

`DS-A1 → DS-H1 → DS-L1 → DS-A2`

不应被理解为四个 executor slice 必须严格串行执行。

存在三个需要纠正的问题：

1. **DS-A1 与 DS-H1 没有真实代码依赖。** DS-A1 定义 Vibe canonical contract；DS-H1 提供 HiThink 的真实 provider evidence。两者应该并行。
2. **DS-A2 放在 DS-L1 之后过晚。** DS-A2 的目的就是在写 Local Fact Lake 前比较 ashare-lake 的 DatasetSpec / PIT / provenance / history_mode 设计，避免先造轮子再审轮子。
3. **DS-L1 前缺少 Existing Data Plane Inventory。** 在建立 Fact Lake 前，必须先确认 Vibe 当前已经有哪些 provider、adapter、cache/store、Data Health、temporal metadata、cross-source compare 与 dataset-like abstraction，避免复制已有能力。

因此 Data Governance Foundation 改为**依赖 DAG**而非串行清单。

---

## 2. Phase 2 Gate 状态

当前技术治理结论：

- Formal Thesis production implementation：独立 review 已通过。
- QA2 concurrency / atomicity contract：`CLOSED`。
- S2D-M production migration safety：`CLOSED`。
- QA3 migration acceptance：`CLOSED`。
- `NORMAL_OPEN_ZERO_MUTATION = CLOSED`。

这些技术合同关闭**不等于**授权 PR Ready / Merge；相关 PR 继续保持 Draft，除非用户单独授权。

Data Governance Foundation 可以继续推进，不再因 Phase 2 QA 尾项人为阻塞新的独立工作线。

---

## 3. 当前执行 DAG

```text
Phase 2 Formal Thesis + Migration/QA technical closure
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
          DS-A1       DS-H1       DS-R1
       Canonical     HiThink     Existing
       Contract      LIVE        Data Plane
         (C)        Evidence     Inventory
                     (Z)          (D)
              │          │          │
              │          │          │
              └────┐     │     ┌────┘
                   │     │     │
                   ▼     │     │
                DS-A2    │     │
             ashare-lake │     │
             Semantic Gap│     │
                Review   │     │
                   │     │     │
                   └─────┴─────┘
                         │
                         ▼
                       DS-L1
                Local Fact Lake PoC
                         │
                         ▼
             Data Governance Foundation
                    acceptance review
                         │
                         ▼
                 Reassess Phase 3+
```

该图表达**逻辑依赖**，不是 executor 锁步。

---

## 4. Wave A — 三条并行线路

### 4.1 DS-A1 — Canonical Data Source Contract v0.1

Owner：Codex / C。

职责：定义 Vibe 自身的 Dataset / Observation / Canonical Fact / Temporal / Provenance / Routing / Reconciliation contract。

DS-A1：

- 不等待 DS-H1；
- 不等待 DS-R1；
- 不接生产 provider；
- 不改变现有 canonical source；
- 完成后必须由 ChatGPT 独立 review。

DS-A1 是 **DS-A2 与 DS-L1 的真实 contract dependency**。

### 4.2 DS-H1 — HiThink LIVE_SMOKE v0.1

Owner：Zcode / Z。

职责：取得 HiThink 实际 provider 行为证据，而不是定义 Vibe canonical contract。

DS-H1：

- 不等待 DS-A1；
- 不等待 DS-R1；
- 不接生产 routing；
- Provider response 始终先视为 Observation；
- 文档能力与 LIVE_VERIFIED 能力必须分开；
- API Key 只允许从本机环境变量读取，不得进入源码、Git、日志、fingerprint、PR 或文档。

DS-H1 **不是整个 DS-L1 的硬 blocker**。

只有当 DS-L1 某个 Dataset 计划使用 HiThink 时，该 Dataset 对应 HiThink capability 必须先达到足够的 live evidence gate；否则 DS-L1 可以使用已批准的其它来源或隔离 fixture 继续 PoC。

### 4.3 DS-R1 — Existing Data Plane Inventory v0.1

Owner：DeepSeek / D。

职责：对 Vibe 当前 integrated data plane 做 exact-head inventory，回答“已经有什么、哪里可以复用、哪里是真缺口”。

该任务只做能力盘点与语义差距分析，不定义新的 DS-A1 contract，不接新 provider，不修改生产实现。

DS-R1 是 **DS-L1 的真实 anti-rewheel dependency**。

---

## 5. Wave B — DS-A2 必须早于 DS-L1

### DS-A2 — ashare-lake Semantic Gap Review

启动 Gate：

`DS-A1_INDEPENDENT_REVIEW = APPROVE`

原因：DS-A2 必须拿 Vibe 已批准的 canonical contract 作为比较基线；在 DS-A1 未冻结前做“gap review”会导致比较目标漂移。

DS-A2 应逐项输出：

- `COPY_CONCEPT`
- `ADAPT`
- `REJECT`
- `NOT_APPLICABLE`

重点覆盖：

- DatasetSpec
- PIT / as_of
- history_mode
- revision / restatement
- provenance
- historical universe / survivorship
- source routing
- local storage / manifests

DS-A2 的目的不是把 ashare-lake 引入生产，而是在 DS-L1 开始前降低重复造轮子与错误抽象风险。

因此旧顺序：

`DS-L1 → DS-A2`

正式修正为：

`DS-A1 approved → DS-A2 → DS-L1`

---

## 6. DS-L1 — Local Fact Lake PoC Start Gate

DS-L1 的硬启动条件：

1. `DS-A1_INDEPENDENT_REVIEW = APPROVE`
2. `DS-R1_EXISTING_DATA_PLANE_INVENTORY = CLOSED`
3. `DS-A2_ASHARE_LAKE_SEMANTIC_GAP = CLOSED`

DS-H1 的处理：

- 若 DS-L1 不依赖 HiThink，可不等待 DS-H1 全能力矩阵完成；
- 若某个 Dataset 使用 HiThink，则该 Dataset 的 HiThink live capability 必须先通过对应证据 Gate；
- HiThink 未通过时禁止用文档宣传能力代替 live evidence。

DS-L1 第一版仍只允许隔离 PoC：

`immutable raw observation → normalize → provenance → repeat ingest → revision detection → as_of query → DuckDB read`

禁止真实用户 DB migration，禁止生产 routing 切换。

---

## 7. Provider Discovery 与 Core Roadmap 的关系

HiThink、FTShare 等 provider capability discovery 属于**证据线路**，不是产品主干依赖。

原则：

- Provider research 可以并行；
- Provider research 不得自动改变 canonical source；
- 不因为发现新 provider 就重新设计已批准 contract；
- FTShare 保持候选，除非 DS-R1 / DS-A1 / DS-L1 暴露明确能力缺口，否则不抢占当前三条核心线路；
- TickDB 继续 Deferred。

---

## 8. Executor Independence Rule

以后固定以下治理规则：

> **一个 executor 只有在存在真实代码/contract dependency 时才等待另一个 executor。测试/验收某个 slice，不等于被测试 executor 不能开始一个独立 slice。**

例如：

`Z 正在验收 C 的功能 A`

只意味着：

`功能 A 最终 closure 等 Z`

不意味着：

`C 不能开始与 A 无依赖的功能 B`

主动 branch 不应为了追随 documentation-only head 演进而持续 rebase/merge；只有当新 North Star amendment 实际改变其 task contract 时才需要显式同步。

---

## 9. 当前优先路线

当前路线冻结为：

```text
Wave A parallel:
  C → DS-A1
  Z → DS-H1 / DS-H1-R1 + actual LIVE evidence
  D → DS-R1 Existing Data Plane Inventory

After DS-A1 approval:
  DS-A2 ashare-lake Semantic Gap Review

After DS-A1 + DS-R1 + DS-A2 closure:
  DS-L1 Local Fact Lake PoC

Then:
  Data Governance Foundation acceptance
  → Reassess Phase 3+
```

该路线 supersede 原 Section 30.5 / 30.6 / 30.7.3 中把 `DS-A1 → DS-H1 → DS-L1 → DS-A2` 理解为严格串行执行的表述。

---

## 10. Safety / Authorization Boundary

本修正案不授权：

- PR Ready / Merge
- stable direct push
- force push
- production provider switching
- canonical source switching
- real-user DB migration
- stable schema activation
- broker integration
- auto trading
- scheduler/background agent

具体当前 executor 授权与 STOP boundary 见 `docs/NEXT_TASK.md`。
