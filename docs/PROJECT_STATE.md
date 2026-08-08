# 项目当前状态

> 稳定分支：`feature/research-system-v01`  
> 稳定 Head：`d06eabac093e0bc0acace4abe1e446b3655629f5`（Merge PR #61，2026-08-08）  
> 当前授权任务：[`docs/NEXT_TASK.md`](NEXT_TASK.md)  
> 产品方向：[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)  
> 治理契约：[`docs/GOVERNANCE.md`](GOVERNANCE.md)  
> 产品候选池：[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)  
> 工程执行规则：根目录 [`AGENTS.md`](../AGENTS.md)

本文件是**项目状态唯一权威**：只描述稳定分支事实、当前授权与总体状态；
不维护 worktree、临时目录、瞬时 CI 等短生命周期信息。GitHub PR/branch 的瞬时状态
必须现场核验。

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

North Star v0.1 是产品方向，不构成代码实施授权；授权仍唯一以
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
| 结构化存储 | 交易流水、决策反馈、决策依据、信号账本、收益归因、告警规则等使用本地持久化 |

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
- Frontend P1 research workspace / AI copilot（PR #56）。

这些“已实现能力”不等于 North Star P0 已完成；P0 仍需要后续 Gap Analysis 判断哪些
现有模块可直接复用、哪些需要重构或新增。

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

PR #59 当前现场状态（2026-08-08 核验）：

- OPEN
- Draft
- mergeable=true
- base=`feature/research-system-v01` @ `d06eabac...`
- head=`agent/frontend-workspace-p2` @ `82856b25e97d14dfd1eb19d78981bb821fdce309`

PR #59 涉及 Stock Workspace、Privacy Mode、resizable desktop AI panel、
`研究 → 筛选 → 逻辑 → 依据 → 持仓 → 复盘` workflow、Decision Priority Rail 与
Workspace P2 浏览器验收。

**停止边界：未经用户单独明确授权，PR #59 不得转 Ready，不得 Merge。**

---

## 6. North Star P0 目标

P0 当前只做**持仓全周期决策闭环**，核心问题：

> 从当前信息看，我现在持有的股票中，哪些需要在下一个可交易时点前重新判断？为什么？

首页方向：

`市场总览 → 持仓 Decision Inbox → 单股深度分析 / Formal Decision`

盘中、盘后、周末分别强调：

- 盘中：风险变化 / Decision Transition
- 盘后：当日事实与 Evidence 更新
- 周末：Thesis Review / 下周准备

P0 不要求同时完成候选股买入分析或全市场 Discovery。

P0 验收必须同时通过：

- **体验验收**：真实日常/盘后/周末使用顺畅；
- **决策质量验收**：能稳定回答市场环境、持仓优先级、HOLD/REDUCE/EXIT 依据、
  支持/反方证据及改变结论的条件。

完整 Product Spec 以 `docs/PRODUCT_NORTH_STAR_V01.md` 为准，不在本文件重复。

---

## 7. 当前授权

- **当前已授权任务：无。**
- **当前已授权产品开发任务：无。**
- North Star v0.1 的记录/合并不自动授权 P0 代码实施。
- PR #59 不授权 Ready/Merge。
- 不授权付费数据、券商连接、自动交易、后台常驻监控或生产 BK-11 ingestion。

下一次需要开发时，应先做只读 Gap Analysis / 工作单设计，用户明确授权后再更新
`docs/NEXT_TASK.md`。

---

## 8. 最近稳定合并（当前重要链）

| PR | Merge SHA | 当前意义 |
|---|---|---|
| #61 | `d06eabac093e0bc0acace4abe1e446b3655629f5` | Screener + sector/market-history recovery chain |
| #60 | `b3b02f3f75152d687b93d5d679105e12d37ee671` | Technical overlays + KDJ + Alert Rules chain |
| #56 | `d848b222cc0ef86414b4e5139b17c6608a1657f6` | Frontend P1 research workspace / AI copilot |
| #57 | `2f8cf81ddc64528152b515fc4e3c645ec0dac19d` | BK-11 zero-cost research recovery |
| #47 | `5d21122c7253186cd80e90722693234eba9fdfab` | Tushare ingestion code；live availability 未证明 |
| #58 | `76356715e375cff698cfe2b5b66e670124470b07` | Public repository governance / README sync |

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
- 文档状态漂移。

这些问题需要在进入更高权限自动化之前处理，但**不能反过来替代产品 North Star**。
任何修复仍需单独授权。

---

## 10. 本地环境边界

本文件不维护瞬时 worktree、备份目录或本地未提交状态。所有本地现场状态必须在可访问
Windows 文件系统时重新执行 `git worktree list` / `git status` 核验后再处理。
