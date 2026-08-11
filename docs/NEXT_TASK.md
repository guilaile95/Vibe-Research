# 当前下一任务

本文件是**当前执行授权与 STOP boundary** 的文档载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，Data Governance 当前执行依赖见
[`docs/PRODUCT_NORTH_STAR_V01_EXECUTION_AMENDMENT_20260810.md`](PRODUCT_NORTH_STAR_V01_EXECUTION_AMENDMENT_20260810.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

> 状态日期：2026-08-10
>
> 说明：本次同步由用户明确授权。当前文档位于 Draft North Star branch；在用户另行授权 Ready / Merge 前，不因此修改 stable、合并任何产品 PR 或迁移真实用户数据。

---

## 1. 当前稳定事实

- Stable branch：`feature/research-system-v01`
- 当前治理使用的 stable exact head：`1be2ecba505a8108740c311c103a2c72d3bcd444`
- Stable 受保护；禁止未经用户单独授权 direct push / force push。

### Phase 2 技术合同状态

- Formal Thesis production implementation：独立 review 已通过。
- QA2 concurrency / atomicity：`CLOSED`。
- S2D-M migration production safety：`CLOSED`。
- QA3 migration acceptance：`CLOSED`。
- `NORMAL_OPEN_ZERO_MUTATION = CLOSED`。

相关 Phase 2 PR 仍保持 Draft；技术合同关闭不等于 Ready / Merge 授权。

---

## 2. 当前已授权执行 DAG

当前不再使用严格串行：

`DS-A1 → DS-H1 → DS-L1 → DS-A2`

而采用：

```text
Wave A parallel
├─ C → DS-A1 Canonical Data Source Contract
├─ Z → DS-H1 HiThink LIVE_SMOKE / R1 + real live evidence
└─ D → DS-R1 Existing Data Plane Inventory

DS-A1 approved
└─ DS-A2 ashare-lake Semantic Gap Review

DS-A1 + DS-R1 + DS-A2 closed
└─ DS-L1 Local Fact Lake PoC

Data Governance Foundation acceptance
└─ Reassess Phase 3+
```

HiThink DS-H1 不是整个 DS-L1 的硬 blocker；只有 DS-L1 某个 Dataset 准备使用 HiThink 时，对应 HiThink capability 才必须先达到 live-evidence gate。

---

## 3. C / Codex — 当前授权

### DS-A1 — Canonical Data Source Contract v0.1

状态：`AUTHORIZED / ACTIVE`

已授权目标：

- Dataset / Observation / Canonical Fact contract
- Temporal semantics
- Provenance
- Dataset-level routing roles
- Reconciliation
- Data Health compatibility boundary
- Local Fact Lake design contract only

边界：

- 不等待 Z / D
- 不接生产 provider
- 不改变现有 canonical source
- 不做 runtime routing change
- 不做 DB migration
- 不开始 DS-L1
- Draft PR only
- `PR_READY = NO`
- `MERGE = NO`

DS-A1 完成后必须由 ChatGPT 独立 review；未 APPROVE 前不得进入 DS-A2 / DS-L1 contract-dependent work。

---

## 4. Z / Zcode — 当前授权

### DS-H1-R1 — HiThink LIVE Harness Contract Closure + Actual LIVE Evidence

状态：`AUTHORIZED / ACTIVE`

PR：`#79`

独立 review 对原 head `a5f5833c7088f27826c739b72d34f49a840c7d9f` 的结论：

`REQUEST_CHANGES`

需要关闭：

1. live test unconditional module skip；
2. `data.item[]` nested response observation / recursive secret sanitization；
3. historical 2 securities × 2 ranges、adjustment matrix、explicit historical `date_ms` limit-up probe 等原 acceptance matrix。

用户已确认 HiThink credential **实际存在**。安全要求：

- 聊天中曾暴露的旧 credential 必须视为 compromised；
- 使用用户重新轮换后的 credential；
- 仅通过本机环境变量 `HITHINK_FINANCE_API_KEY` 提供；
- 禁止进入源码、测试 fixture、Markdown、PR、Git、stdout/stderr、日志、observation、fingerprint；
- 不在任何报告中写 credential value。

R1 修完后，如果本机 credential 可读，必须直接执行真实 LIVE_SMOKE，不再停在 `BLOCKED_LIVE_AUTH`。

边界：

- probe/test only
- no production HiThink adapter
- no provider routing
- no canonical switching
- no Fact Lake
- no real-user DB
- `PR_READY = NO`
- `MERGE = NO`

---

## 5. D / DeepSeek — 当前授权

### DS-R1 — Existing Data Plane Inventory v0.1

状态：`AUTHORIZED / START_NOW`

目标：在 DS-L1 前建立 exact-head Vibe integrated data-plane inventory，回答：

> **Vibe 已经有哪些数据能力、哪些可以直接复用、哪些只需要扩展、哪些才是真正需要 Data Governance / Fact Lake 新建的缺口？**

D 不定义 DS-A1 contract，不接新 provider，不实现 Fact Lake。

详细工作单由 ChatGPT 当前会话下发。

建议证据基线：

- Vibe integrated stable：`feature/research-system-v01@1be2ecba505a8108740c311c103a2c72d3bcd444`
- 已验收但尚未 merge 的 subsystem 必须单独标记 branch/SHA，不得与 stable 混写。
- HiThink / DS-A1 未完成内容只能作为 `IN_PROGRESS / NOT_INTEGRATED`，不得伪装成 current integrated capability。

边界：

- docs / inventory / analysis only
- no production code changes
- no provider/network integration
- no canonical switching
- no real-user DB
- no Ready / Merge

---

## 6. 后续 Gate — 已冻结但当前未授权自动开始

### DS-A2 — ashare-lake Semantic Gap Review

启动条件：

`DS_A1_INDEPENDENT_REVIEW = APPROVE`

DS-A2 必须先于 DS-L1，输出：

- `COPY_CONCEPT`
- `ADAPT`
- `REJECT`
- `NOT_APPLICABLE`

未到 Gate 不自动开始。

### DS-L1 — Local Fact Lake PoC v0.1

硬启动条件：

1. `DS_A1_INDEPENDENT_REVIEW = APPROVE`
2. `DS_R1_EXISTING_DATA_PLANE_INVENTORY = CLOSED`
3. `DS_A2_ASHARE_LAKE_SEMANTIC_GAP = CLOSED`

仍只允许隔离 PoC；不迁移真实用户数据库，不切 production routing。

---

## 7. 当前显式停止边界

未经用户单独授权，禁止：

- PR Ready
- Merge
- force push
- stable direct push
- stable schema activation
- real-user DB migration
- production canonical-source switching
- broker connection / order execution / auto trading
- Scheduler / Background Agent
- 自动进入 Phase 3+

继续保持：

- PR #64 blocked / no auto-handling
- PR #69 duplicate/superseded Draft / leave alone
- 用户本地 `AGENTS.md` 不触碰
- `AI与A股每日简报` automation 不触碰

---

## 8. Executor Independence Rule

固定规则：

> Executor 只有在存在真实代码或 contract dependency 时才等待另一个 executor。

例如 Z 在验证 C 的功能 A，只表示 A 的最终 closure 依赖 Z；不表示 C 不能开始与 A 无依赖的功能 B。

Documentation-only branch head 变化也不要求所有 active executor branch 持续同步；只有文档变更实际改变该 executor 的 task contract 时才显式同步。

---

## 9. 当前产品优先级

North Star v0.1 的长期产品优先级仍保持：

1. P0：持仓全周期决策闭环
2. P1：候选股买入决策
3. P2：全市场机会发现
4. P3：Outcome / Behavioral / Calibration / Model Governance

但当前已确认的近期 Gate 是：

`Phase 2 technical closure → Data Governance Foundation → reassess Phase 3+`

Data Governance Foundation 是为了让 Evidence / Thesis / Decision 建立在可追溯、时间语义正确、可复查的数据事实层上，不改变最终产品的 Capital-First 目标。
