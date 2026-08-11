# 当前下一任务

本文件是**当前执行授权与 STOP boundary** 的文档载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

> 状态日期：2026-08-12
>
> 说明：Project Consolidation Gate **已关闭**（PR #98 MERGED）。
> P0-DI0 **已关闭**。当前执行 Wave 为 **P0-DI1**。
> 本文件是执行授权，不是 North Star 重写。

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

Stable 受保护；禁止未经用户单独授权 direct push / force push。

### 已进入 stable 的 P0 foundation（摘要）

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

### P0-DI0 状态（CLOSED）

```text
P0_DI0_INTERNAL_GAP_MAP = COMPLETE
P0_DI0_PRODUCT_ACCEPTANCE = COMPLETE
P0_DI0_ARCHITECTURE_DECISION = CLOSED
```

---

## 2. 当前阶段与 Wave

```text
阶段 = P0 PRODUCTIZATION
```

当前 Wave：

```text
P0-DI1
Decision Inbox Pure Projection Core v0.1
```

```text
NEXT_SLICE =
P0-DI1 Decision Inbox Pure Projection Core v0.1

DI1_EXECUTOR = K
```

### DI1 已冻结架构（摘要，非重新设计）

```text
Decision Inbox =
PURE CAMPAIGN-LEVEL READ-MODEL PROJECTION

Decision Unit =
Security + Strategy + Campaign

NEW_PERSISTENCE = NO
NEW_DB = NO
NEW_TABLE = NO

AI_AUTO_CALL = NO
NUMERIC_PRIORITY_SCORE = NO
CAMPAIGN_CAPITAL_RELEVANCE = UNKNOWN

TOP_RISK != HARD_RISK AUTHORITY
decision_cockpit_today != DI semantic authority
```

### DI1 production scope（仅允许）

```text
backend/decision_inbox_projection.py
backend/tests/test_decision_inbox_projection.py
```

可选：

```text
docs/p0/DECISION_INBOX_PROJECTION_V01.md
```

核心边界：

```text
NO I/O
NO SQLite
NO filesystem
NO network
NO FastAPI
NO AI
NO wall clock
NO new persistence
NO BUY/SELL generation
NO numeric priority score
```

---

## 3. 当前用户授权任务

| Lane | 授权 | 说明 |
|---|---|---|
| **K** | **AUTHORIZED** | Primary Implementer；P0-DI1 production implementation |
| **Z** | **COMPLETE / FREE** | DI0 product acceptance 已完成；当前 FREE |
| **C** | **REST / FREE** | 非 DI1 production executor |
| **ChatGPT** | **AUTHORIZED** | architecture authority / independent reviewer |

```text
K = AUTHORIZED
ROLE = Primary Implementer
SLICE = P0-DI1

Z = COMPLETE / FREE
C = REST / FREE

ChatGPT =
architecture authority / independent reviewer
```

明确：

```text
C is NOT pre-authorized for DI1.
C_PREAUTHORIZED = NO
DI1_EXECUTOR = K
```

当前禁止（超出 DI1 pure-projection scope）：

- 超出允许文件列表的 production 实现
- I/O / SQLite / network / FastAPI / AI / wall-clock 接入
- 新建 persistence / DB / table
- BUY/SELL generation / numeric priority score
- Sell Engine / 新 Formal Decision 产品切片（未单独授权）
- 以 North Star unchecked item 为借口的 feature sprint
- 将 C 预选或自动指派为 DI1 executor

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

本 Wave **只推进 Decision Inbox pure projection core v0.1**，不授权整条主链实现。

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

但 **当前唯一执行 Wave 是 P0-DI1**，不是并行开启 P1/P2/P3。

---

## 7. 后续（均未授权自动开始）

- DI1 之后的 Decision Inbox I/O adapter / product surface（需新授权）
- Sell Engine / Next Best Action productization
- Frontend information architecture rework（替代 PR #59 路径）
- Market Regime production path（PR #64 当前 BLOCKED）
- H4 / 新 provider / 新 Fact Lake dataset
- 历史 docs nonblocking cleanup（PRODUCT_BACKLOG / integration registry / PR #79 等）
