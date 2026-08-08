# 当前下一任务

本文件是**唯一当前授权任务**的载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**P0-S1A — Legacy Bootstrap & Position Reconciliation v0.1**

P0 North Star（持仓全周期决策闭环）的第一个实施 Slice，只解决一个基础问题：

> Vibe 从正式接管账户的那一天开始，如何准确、可审计地知道我实际持有哪些股票，
> 而不伪造 Vibe 之前的交易历史？

建立事实链：

`Ledger Start → ACCOUNT_OPENING → LEGACY_POSITION_OPENING → post-Vibe trade events
→ derived positions → reconciliation`

**Scope（本轮必须交付）**：

- `ACCOUNT_OPENING`：ledger 接管边界（`ledger_start_at`、opening cash、`provenance=MANUAL`、
  `PRE_VIBE_HISTORY=UNKNOWN`）；不制造接管日期之前的事件。
- `LEGACY_POSITION_OPENING`：期初持仓事件（code / shares / known cost basis /
  `origin=PRE_VIBE` / `acquired_before_vibe=true` / `historical_trades=UNKNOWN`）；
  明确 **≠ BUY**，不根据当前成本价反推历史买入。
- `CORRECTION`：append-only 显式修正事件（被修正对象、修正前后差异、reason、timestamp），
  禁止静默改写历史事件。
- Position Derivation：从 Opening + post-Vibe BUY/ADD/REDUCE/SELL + CORRECTION 确定性推导
  shares / cost basis / position state；复用 performance attribution 已验证的加权平均成本逻辑；
  shares 不得为负；超额卖出 fail closed；full exit → 0 shares。
- Reconciliation：只读对比 ledger-derived positions vs portfolio.json holdings，输出
  MATCH / MISMATCH / MISSING_IN_LEDGER / MISSING_IN_PORTFOLIO，不自动覆盖任何一方。
- Bootstrap 显式且幂等：preview/dry-run 校验 + commit 校验；同一 Ledger Start 不得重复创建；
  已存在 post-Vibe ledger 数据时拒绝 bootstrap。

**Stop boundary**：

- Draft PR + CI / 独立审查证据形成后 STOP。

**Non-goals（本轮明确不做）**：

- campaign_id / Campaign（属于 P0-S2）
- NAV / drawdown（属于 P0-S1B）
- 将 portfolio.json 替换为 ledger canonical source（switchover 需另行授权；本轮
  ledger-derived position 只是 candidate canonical fact chain）
- Thesis 改造 / Evidence Delta / Market & Sector Regime / Risk & Sell Engine /
  Decision Inbox / Next Best Action / Formal Decision / Outcome 系统
- Scheduler / Background Agent / Broker / BaoStock production ingestion / Tushare
- 前端改动 / UI redesign / 无关重构 / PR #59 修复

## 当前产品优先级（方向，不是授权）

North Star v0.1 采用 **Capital-First**：

1. **P0：持仓全周期决策闭环**；
2. P1：候选股买入决策；
3. P2：全市场机会发现；
4. P3：Outcome / Behavioral / Calibration / Model Governance。

P0 的目标不是“盘中必须做交易”，而是：

> 从当前信息看，我现在持有的股票中，哪些需要在下一个可交易时点前重新判断？为什么？

首页主流程方向：

`市场总览 → 持仓 Decision Inbox → 单股深度分析 / Formal Decision`

完整产品决策见 `docs/PRODUCT_NORTH_STAR_V01.md`，本文件不复制细节。

## 当前显式停止边界

- **PR #59 保持 Draft；未经单独明确授权，不得转 Ready，不得 Merge。**
- **P0-S1A Draft PR 不得转 Ready / Merge，直到独立审查证据形成。**
- **P0-S1B / P0-S2（Campaign）/ Decision Inbox 等后续切片未授权。**
- North Star v0.1 不授权生产数据接入、Scheduler、Background Agent、券商连接、
  付费数据源或自动交易。
- 暂不购买 Tushare 等商业数据；付费数据不是基础产品依赖。
- BK-11 zero-cost research 已作为研究成果进入稳定历史；不因此自动授权生产 BaoStock
  ingestion / scheduler / backfill / Slice 4。
- PR #47 已合并进入稳定分支，但其历史 live-smoke 仍为
  `LIVE_SMOKE_BLOCKED_CREDENTIAL`；不得据此宣称 Tushare 生产可用。

## 最近稳定事实（用于避免旧交接误导）

- 稳定分支：`feature/research-system-v01`。
- 2026-08-09 现场核验稳定 Head：`9b9f0bfa1c4d6725bc4071221f3e9ef22d7a1b23`
  （Merge PR #61 后 6 个 North Star 文档提交）。
- 当前任务分支：`feat/p0-position-reality-bootstrap-v0.1`（基于上述稳定 Head）。
- PR #47 已合并：Merge `5d21122c7253186cd80e90722693234eba9fdfab`；
  代码存在不等于 Tushare Token/权限/live 可用性已证明。
- PR #56 已合并：Frontend P1 research workspace / AI copilot。
- PR #57 已合并：BK-11 zero-cost source research，结论保持
  `FEASIBLE_ZERO_COST_PARTIAL` / `legal-zero = NOT_PROVEN`。
- PR #60 已合并：K-line technical overlays / KDJ / Alert Rules chain。
- PR #61 已合并：Screener / sector flow / northbound history chain。
- PR #59 当前仍是 UI-P2 Draft，等待独立人类视觉签字边界。

## 后续候选（均未授权）

- **P0-S1B**：NAV / Drawdown（依赖 P0-S1A 的 opening state）。
- **P0-S2**：Campaign（Security + Strategy + Campaign 正式决策单元）。
- 对抗性审查发现的安全/可靠性/Foundation 项：CLI 权限边界、local API trust、
  alert-rule concurrency test harness、文档漂移、SSRF hardening 等；这些属于
  Foundation/Hardening lane，不自动覆盖产品优先级，也未授权实施。
- Engineering Reliability 后续 lint/type/coverage 等候选继续未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
