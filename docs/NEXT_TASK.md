# 当前下一任务

本文件是**当前执行授权与 STOP boundary** 的文档载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，Data Governance 执行修订见
[`docs/PRODUCT_NORTH_STAR_V01_EXECUTION_AMENDMENT_20260810.md`](PRODUCT_NORTH_STAR_V01_EXECUTION_AMENDMENT_20260810.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

> 状态日期：2026-08-12
>
> 说明：本文件在 **Project Consolidation Gate** 的 synthetic integration candidate 上收敛。
> **不等于** stable merge；`PR_READY = NO`，`MERGE = NO`，`REAL_USER_DB_MIGRATION = NO`。

---

## 1. 当前稳定事实

- Stable branch：`feature/research-system-v01`
- 当前治理使用的 stable exact head：`1be2ecba505a8108740c311c103a2c72d3bcd444`
- Stable 受保护；禁止未经用户单独授权 direct push / force push
- 本 consolidation branch：`integration/project-consolidation-v0.1`（synthetic candidate only）

### 独立 accepted 但尚未进入 stable 的核心能力（摘要）

| Domain | 代表 PR | 状态 |
|---|---|---|
| Formal Thesis lifecycle / projection | #72 / #73 / QA #74–#77 | accepted-not-merged；Draft |
| Campaign re-entry lineage | #87 | accepted-not-merged；Draft |
| Frozen Decision / Attribution / PA / Outcome | #88 / #89 / #92 / #95 | accepted-not-merged；Draft；#91 superseded by #95 |
| Data Governance North Star + DS-A1/R1/A2 | #78 / #80 / #81 / #82 | accepted-not-merged；Draft |
| Fact Lake S1A–S3 + Q1 | #83–#86 / #94 / #97 | accepted-not-merged；Draft |
| Fact Lake Health H1–H3 | #90 / #93 / #96 | accepted-not-merged；Draft |

独立 acceptance ≠ Ready / Merge 授权。

---

## 2. 当前授权任务

**Project Consolidation Gate / Integration Freeze**

状态：`AUTHORIZED / ACTIVE`（synthetic integration only）

目标：

1. 重建 accepted-head registry + supersession registry + exact dependency DAG
2. 在同一 synthetic integration head 收敛 Q1 + H3 与核心 P0 foundation
3. 完成 integrated regression + migration rehearsal（temp DB only）
4. 输出 exact future Merge DAG
5. **STOP before Ready / Merge**

明确 NOT_AUTHORIZED：

- PR Ready / Merge / force push / stable direct push
- real-user DB migration / production schema activation
- production canonical-source switching
- broker / auto trading / Scheduler / Background Agent
- 新的 product/domain/data feature 开发（North Star unchecked item 不是自动 backlog）
- PR #59 Frontend P2 纳入 integration
- PR #64 Market Regime / PR #69 自动处理

---

## 3. 历史 Wave 状态（已关闭为 acceptance，非 merge）

以下 Wave 在各自 PR 上独立验收关闭，**不**表示已进入 stable：

```text
DS-A1 Canonical Contract        CLOSED (accepted head #80)
DS-R1 Existing Data Plane       CLOSED (accepted head #81)
DS-A2 ashare-lake Gap Review    CLOSED (accepted head #82)
DS-L1 S1A/S1B/S1C/S2/S3/Q1      CLOSED as independent slices
DS-L1 H1/H2/H3                  CLOSED as independent slices
Formal Thesis non-migration     CLOSED as independent slices
Formal Thesis migration tooling CLOSED as independent slices (NOT real-user executed)
Decision / Outcome chain        CLOSED as independent slices (#95 supersedes #91)
```

当前剩余真正的 Gate：

```text
accepted-but-fragmented
        ↓
synthetic integration candidate
        ↓
independent review (ChatGPT)
        ↓
user-authorized Ready / Merge (NOT this task)
```

---

## 4. 当前显式停止边界

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
- 自动进入新的 product feature sprint

继续保持：

- PR #59 OUT_OF_SCOPE for this consolidation
- PR #64 blocked / DO NOT TOUCH
- PR #69 duplicate/superseded Draft / leave alone
- PR #91 superseded by #95 / DO NOT MODIFY / do not integrate as authority
- 用户本地 `AGENTS.md` 不触碰
- `AI与A股每日简报` automation 不触碰

---

## 5. 当前产品优先级（方向，不是自动实现 backlog）

North Star v0.1 的长期产品优先级仍保持：

1. P0：持仓全周期决策闭环
2. P1：候选股买入决策
3. P2：全市场机会发现
4. P3：Outcome / Behavioral / Calibration / Model Governance

但 **当前** 唯一授权 Gate 是 Project Consolidation，不是继续逐项开发 North Star unchecked items。

---

## 6. 后续（均未授权自动开始）

- 将 synthetic integration candidate 标记 Ready（需要用户 + ChatGPT）
- 按 exact Merge DAG 合并进入 stable
- Real-user Formal Thesis migration
- Frontend information architecture rework（替代 PR #59 路径）
- Market Regime production path（PR #64 当前 BLOCKED_BY_SOURCE_METADATA）
- H4 / Decision Inbox / Sell Engine / 新 provider / 新 Fact Lake dataset
