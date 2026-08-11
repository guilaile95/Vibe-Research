# 当前下一任务

本文件是**当前执行授权与 STOP boundary** 的文档载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

> 状态日期：2026-08-12
>
> 说明：Project Consolidation Gate **已关闭**（PR #98 MERGED）。
> 当前阶段切换到 **P0 Productization**。本文件是执行授权，不是 North Star 重写。

```text
North Star = product authority
NEXT_TASK  = current execution authority
```

---

## 1. 当前稳定事实

- Stable branch：`feature/research-system-v01`
- Stable exact head：`7bd04a58dee44d613b97b302b6401a1256d753ff`
- PR #98：**MERGED**
- Project Consolidation Gate：**CLOSED**
- Real-user Formal Thesis migration：

```text
REAL_USER_FORMAL_THESIS_MIGRATION = NOT_REQUIRED
MIGRATION_STATUS = NOT_REQUIRED_NO_EXISTING_DB
```

（runtime 权威路径下不存在既有 `evidence_thesis.db`；未伪造 v1 库。）

Stable 受保护；禁止未经用户单独授权 direct push / force push。

### 已进入 stable 的 P0 foundation（摘要）

以下能力已通过 Consolidation Merge 进入 stable（**不要再写 accepted-not-merged**）：

- Formal Thesis
- Current Thesis **OPTION A**（pure core + I/O adapter）
- Campaign Re-entry Lineage
- Frozen Decision
- Decision ↔ Trade Attribution
- Performance Attribution Provenance
- Formal Decision Outcome
- Fact Lake S1A–S3
- Publication Selection Q1
- Fact Lake Health H1 / H2 / H3

Foundation in stable ≠ P0 产品闭环完成。

---

## 2. 当前阶段与 Wave

```text
阶段 = P0 PRODUCTIZATION
目标 = Decision Inbox Readiness / First Vertical Slice
```

当前 Wave：

```text
P0-DI0
Decision Inbox Reuse / Contract Freeze
```

目标：

1. 在 exact stable head 上做 Decision Inbox **internal anti-rewheel / gap map**
2. 冻结 Decision Inbox **product acceptance contract**
3. 由 ChatGPT 给出 architecture decision + next-slice authorization
4. **在 DI0 Gate 关闭前，不开始 production implementation**

---

## 3. 当前用户授权任务

| Lane | 授权 | 说明 |
|---|---|---|
| **K** | **AUTHORIZED** | Decision Inbox internal anti-rewheel / exact-head gap map |
| **Z** | **AUTHORIZED** | Decision Inbox product acceptance contract |
| **ChatGPT** | **AUTHORIZED** | architecture decision + next-slice authorization |
| **C** | **NO PRODUCTION IMPLEMENTATION YET** | 等待 DI0 Gate 关闭；这是**依赖 Gate**，不是无限冻结 |

C 在 DI0 关闭后可进入下一授权切片；在此之前禁止：

- Decision Inbox production UI/API 实现
- Sell Engine / 新 Formal Decision 产品切片实现
- 以 North Star unchecked item 为借口的 feature sprint

---

## 4. P0 主链（方向，不是本 Wave 的自动 backlog）

保持 North Star P0 主链：

```text
市场总览
→ 持仓 Decision Inbox
→ Campaign / Current Thesis
→ Evidence / Risk
→ Sell Engine
→ Asset / Trade / Portfolio
→ Next Best Action
→ Frozen Decision
→ 手工实际交易
→ Outcome
```

本 Wave **只推进 Decision Inbox readiness / contract freeze**，不授权整条主链实现。

---

## 5. 当前显式停止边界

未经用户单独授权，禁止：

- PR Ready / Merge / force push / stable direct push
- new provider
- new dataset
- Fact Lake expansion
- H4 background runtime
- broker connection / order execution / auto trading
- Scheduler / Background Agent expansion
- production canonical-source switching
- PR #59 Ready/Merge
- PR #64 修改
- PR #69 修改
- 用户本地 `AGENTS.md` 修改
- `AI与A股每日简报` automation 触碰

继续保持：

- PR #91 superseded by #95（历史 supersession；stable 以 #95 为准）
- PR #64 Market Regime：`BLOCKED_BY_SOURCE_METADATA` / DO NOT TOUCH
- 不把 Consolidation registry 当作 runtime authority

---

## 6. 当前产品优先级（方向）

North Star v0.1 长期产品优先级仍保持：

1. P0：持仓全周期决策闭环
2. P1：候选股买入决策
3. P2：全市场机会发现
4. P3：Outcome / Behavioral / Calibration / Model Governance

但 **当前唯一执行 Wave 是 P0-DI0**，不是并行开启 P1/P2/P3。

---

## 7. 后续（均未授权自动开始）

- DI0 关闭后的 Decision Inbox first vertical slice implementation（需新授权）
- Sell Engine / Next Best Action productization
- Frontend information architecture rework（替代 PR #59 路径）
- Market Regime production path（PR #64 当前 BLOCKED）
- H4 / 新 provider / 新 Fact Lake dataset
- 历史 docs nonblocking cleanup（PRODUCT_BACKLOG / integration registry / PR #79 等）
