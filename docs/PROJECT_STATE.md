# 项目当前状态

> 稳定分支：`feature/research-system-v01`
> 稳定 exact head：`7bd04a58dee44d613b97b302b6401a1256d753ff`
> （Merge PR #98 Project Consolidation Candidate；Consolidation Gate **CLOSED**）
> 当前授权任务：[`docs/NEXT_TASK.md`](NEXT_TASK.md) — **P0 Productization / P0-DI1**
> 产品方向：[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)
> 治理契约：[`docs/GOVERNANCE.md`](GOVERNANCE.md)
> 产品候选池：[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)
> 工程执行规则：根目录 [`AGENTS.md`](../AGENTS.md)
> Consolidation registry（历史元数据，非 runtime authority）：[`docs/integration/`](integration/)

本文件描述**稳定分支事实**与当前治理阶段。

```text
Stable branch = feature/research-system-v01
Stable exact head = 7bd04a58dee44d613b97b302b6401a1256d753ff
PR #98 = MERGED
Project Consolidation Gate = CLOSED
Real-user Formal Thesis migration = NOT_REQUIRED_NO_EXISTING_DB
```

GitHub PR/branch 的瞬时状态必须现场核验。

---

## 1. 当前产品身份与方向

2026-08-08 用户完成第一性原则产品方向收敛，North Star v0.1 已记录在
`docs/PRODUCT_NORTH_STAR_V01.md`。

产品身份：

> **Single-user Personal Local Investment OS：个人、本地的 A 股投资研究与决策系统。**

核心使命：围绕真实持仓与拟交易标的，减少买入、持有、卖出中的错误决策风险，
同时改善长期收益；不是实时行情终端、自动交易系统或每日股票推荐器。

当前优先级采用 Capital-First：

1. **P0：持仓全周期决策闭环**；
2. P1：候选股买入决策；
3. P2：全市场机会发现；
4. P3：Outcome / Behavioral / Calibration / Model Governance。

```text
North Star = product authority（产品方向）
NEXT_TASK  = current execution authority（当前执行授权）
```

North Star v0.1 不构成代码实施授权；当前执行授权仍唯一以
`docs/NEXT_TASK.md` 为准。

---

## 2. 当前系统形态

| 层级 | 当前实现 |
|---|---|
| 仓库 | Public；MIT License；default/stable branch 为 `feature/research-system-v01` |
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind；默认开发端口 `:5899` |
| 后端 | FastAPI + Uvicorn；默认端口 `:8900` |
| A 股数据 | `backend/astock.py`、`backend/market.py`、本地/公开数据链；受控缓存与降级 |
| 全球上下文 | `backend/gstock.py` + `global-stock-data/`；用于市场/产业上下文，不是当前正式交易 Universe |
| 用户数据 | 本地用户目录 / `VR_DATA_DIR` / localStorage；持仓、账户、模型密钥不进 Git |
| 结构化存储 | 交易流水、决策反馈、决策依据、信号账本、收益归因、告警规则、Campaign、Formal Thesis / Frozen Decision / Fact Lake 等使用本地持久化 |

---

## 3. 稳定分支已具备的关键能力

稳定分支当前已经具备多条可复用链路：

- 每日复盘、市场宽度、板块/行业研究与市场环境聚合；
- 持仓、账户资金、结构化持仓建议与现有执行约束；
- Trade Ledger、Decision Feedback、Decision Evidence、Signal Ledger、收益归因；
- Data Health 与数据 freshness/availability 观测；
- Intel Daily Digest；
- 技术指标展示与 K-line overlays，包括 KDJ（PR #60）；
- Alert Rule evaluator/store/API（PR #60）；
- Screener、行业资金历史、北向资金历史链（PR #61）；
- Frontend P1 research workspace / AI copilot（PR #56）；
- **P0 Foundation（2026-08-09 集成完成）**：
  - Account Reality（`GET /api/account/reality`）：cash 双源 + settled 定价 +
    settled NAV candidate（PR #65）；
  - Manual Cash Events + Cash Correction + Effective Cash Facts
    （`/api/account/cash-events*`，PR #67）；
  - Campaign Core（Identity / Strategy / Lifecycle Transition / Thesis Binding，
    `/api/campaigns*`，PR #66）；
  - Alert Rule 并发初始化可靠性修复（PR #68）；
  - Foundation Router Wiring：cash/campaign 路由正式挂载 main app（PR #70）。

### Project Consolidation 后已进入 stable 的 P0 foundation（PR #98）

以下能力已通过 PR #98 **Merge 进入 stable**（不再描述为 accepted-not-merged）：

| Domain | Stable 状态 |
|---|---|
| Formal Thesis lifecycle / schema / mutation gates | **in stable** |
| Current Thesis projection **OPTION A**（pure core domain authority + I/O adapter） | **in stable** |
| Campaign Re-entry Lineage | **in stable** |
| Frozen Decision Snapshot Ledger | **in stable** |
| Decision ↔ Trade Attribution | **in stable** |
| Performance Attribution Provenance | **in stable** |
| Formal Decision Outcome | **in stable**（#91 superseded by #95） |
| Fact Lake S1A–S3 | **in stable** |
| Canonical Publication Selection Q1 | **in stable** |
| Fact Lake Health H1 / H2 / H3 | **in stable** |

这些“已进入 stable 的 foundation”**不等于** North Star P0 产品闭环已完成。
P0 Productization 仍需要 Decision Inbox 等产品切片的 gap map / contract / 授权实现。

### Real-user Formal Thesis DB

现场核验（stable exact head）：

```text
RESOLVED_REAL_USER_DB_PATH =
C:\Users\DINOL\.vibe-research\evidence_thesis.db

REAL_USER_FORMAL_THESIS_MIGRATION = NOT_REQUIRED
MIGRATION_STATUS = NOT_REQUIRED_NO_EXISTING_DB
```

路径下不存在既有 Evidence Thesis ledger；**未**伪造 v1 DB，**未**执行 migrate。
后续首次写入将按 stable v2 schema 创建，而非 v1→v2 迁移。

---

## 4. 数据与 BK-11 当前事实

### Tushare

PR #47 已合并进入稳定分支：Merge
`5d21122c7253186cd80e90722693234eba9fdfab`。

但其历史 live-smoke 结论仍是：

- `LIVE_SMOKE_BLOCKED_CREDENTIAL`
- `TUSHARE_TOKEN=missing`
- 未执行 live 请求
- 未证明生产可用性

因此：**代码存在 ≠ Token/权限/live 可用性已证明。**

产品方向当前明确：暂不购买 Tushare 等商业数据，付费数据不是基础产品依赖。

### BaoStock / zero-cost research

PR #57 已合并：Merge `2f8cf81ddc64528152b515fc4e3c645ec0dac19d`。

研究结论保持：

- `FEASIBLE_ZERO_COST_PARTIAL`
- `legal-zero = NOT_PROVEN`
- BaoStock 可支持历史股票池、日行情、停牌、breadth 等零成本能力
- 这仍是 research/harness/test/docs，不等于生产 BaoStock ingestion 已授权

BK-11 production ingestion / scheduler / backfill / Slice 4 当前仍无授权。

---

## 5. 当前 UI / Frontend 状态

PR #56 已合并：Merge `d848b222cc0ef86414b4e5139b17c6608a1657f6`，稳定分支拥有
Vibe-specific research workspace 与 AI copilot 基线。

PR #59 仍是大型 Frontend P2 Draft：

- 设计早于 Formal Thesis / Frozen Decision / Fact Lake Health
- **不得因 CI green 自动纳入 productization**
- **未经用户单独明确授权，不得转 Ready，不得 Merge**

---

## 6. North Star P0 目标

P0 当前只做**持仓全周期决策闭环**，核心问题：

> 从当前信息看，我现在持有的股票中，哪些需要在下一个可交易时点前重新判断？为什么？

P0 主链（产品方向，不是自动实现 backlog）：

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

首页方向：

`市场总览 → 持仓 Decision Inbox → 单股深度分析 / Formal Decision`

P0 不要求同时完成候选股买入分析或全市场 Discovery。

P0 验收必须同时通过：

- **体验验收**：真实日常/盘后/周末使用顺畅；
- **决策质量验收**：能稳定回答市场环境、持仓优先级、HOLD/REDUCE/EXIT 依据、
  支持/反方证据及改变结论的条件。

完整 Product Spec 以 `docs/PRODUCT_NORTH_STAR_V01.md` 为准，不在本文件重复。

---

## 7. 当前授权

```text
P0-DI0 = CLOSED
P0-DI1 = AUTHORIZED
DI1_EXECUTOR = K
C = REST / FREE
C_PREAUTHORIZED = NO
```

- **当前阶段：P0 PRODUCTIZATION**
- **当前 Wave：P0-DI1 — Decision Inbox Pure Projection Core v0.1**
- **K = AUTHORIZED**（Primary Implementer；DI1 pure projection 实现）
- **Z = COMPLETE / FREE**（DI0 product acceptance 已完成）
- **C = REST / FREE**（**不是** DI1 production executor；`C is NOT pre-authorized for DI1`）
- **ChatGPT** = architecture authority / independent reviewer
- DI1 scope 仅允许 pure-domain projection 文件（见 `docs/NEXT_TASK.md`）；
  禁止 I/O / SQLite / FastAPI / AI / new persistence / numeric priority score
- North Star unchecked items 不自动成为 implementation backlog
- PR #59 不授权 Ready/Merge
- PR #64 / #69：DO NOT TOUCH
- 不授权：new provider / new dataset / Fact Lake expansion / H4 background runtime /
  broker / auto trading / Scheduler / Background Agent expansion /
  production canonical-source switch

---

## 8. 最近稳定合并（当前重要链）

| PR | 当前意义 |
|---|---|
| **#98** | **Project Consolidation Candidate Merge**（Q1+H3+Thesis+Decision foundation 进入 stable） |
| #71 | P0 foundation state sync docs |
| #70 | P0 Foundation Router Wiring |
| #67 | Manual Cash Events + Correction + Effective Cash Facts |
| #65 | Account Reality & Settled NAV candidate |
| #66 | Campaign Core + Lifecycle + Thesis Binding |
| #68 | Alert Rule 并发初始化可靠性修复 |
| #61 | Screener + sector/market-history recovery chain |
| #60 | Technical overlays + KDJ + Alert Rules chain |
| #56 | Frontend P1 research workspace / AI copilot |
| #57 | BK-11 zero-cost research recovery |
| #47 | Tushare ingestion code；live availability 未证明 |
| #58 | Public repository governance / README sync |

---

## 9. 已知 Foundation / Hardening 方向（未授权）

对抗性审查已识别若干 Foundation/Hardening 候选，包括：

- browser → local AI CLI 权限链，尤其浏览器触发 CLI 的宽权限模式；
- localhost API trust boundary / CORS / optional auth；
- alert-rule concurrency test harness 的 thread + process-global reload 设计；
- SSRF redirect/DNS TOCTOU hardening；
- API resource budgeting；
- localStorage secret exposure 风险；
- RSS response-size 限制；
- 历史文档状态漂移（nonblocking cleanup，不自动扩 scope）。

这些问题需要在进入更高权限自动化之前处理，但**不能反过来替代产品 North Star**。
任何修复仍需单独授权。

本轮已闭合项：alert-rule concurrency flake（P0-0C，PR #68）；Project Consolidation Gate（PR #98）。

---

## 10. 本地环境边界

本文件不维护瞬时 worktree、备份目录或本地未提交状态。所有本地现场状态必须在可访问
Windows 文件系统时重新执行 `git worktree list` / `git status` 核验后再处理。
