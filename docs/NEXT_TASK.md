# 当前下一任务

本文件是**唯一当前授权任务**的载体；项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，产品方向见
[`docs/PRODUCT_NORTH_STAR_V01.md`](PRODUCT_NORTH_STAR_V01.md)，产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**无。**

**当前已授权产品开发任务：无。**

产品方向已经在 `docs/PRODUCT_NORTH_STAR_V01.md` 冻结为 v0.1，但该文档本身
**不构成代码实施授权**。下一步如果要开始 P0 开发，必须由用户明确授权后再更新本文件。

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
- North Star v0.1 不授权 P0 代码实施、生产数据接入、Scheduler、Background Agent、
  券商连接、付费数据源或自动交易。
- 暂不购买 Tushare 等商业数据；付费数据不是基础产品依赖。
- BK-11 zero-cost research 已作为研究成果进入稳定历史；不因此自动授权生产 BaoStock
  ingestion / scheduler / backfill / Slice 4。
- PR #47 已合并进入稳定分支，但其历史 live-smoke 仍为
  `LIVE_SMOKE_BLOCKED_CREDENTIAL`；不得据此宣称 Tushare 生产可用。

## 最近稳定事实（用于避免旧交接误导）

- 稳定分支：`feature/research-system-v01`。
- 2026-08-08 现场核验稳定 Head：`d06eabac093e0bc0acace4abe1e446b3655629f5`
  （Merge PR #61）。
- PR #47 已合并：Merge `5d21122c7253186cd80e90722693234eba9fdfab`；
  代码存在不等于 Tushare Token/权限/live 可用性已证明。
- PR #56 已合并：Frontend P1 research workspace / AI copilot。
- PR #57 已合并：BK-11 zero-cost source research，结论保持
  `FEASIBLE_ZERO_COST_PARTIAL` / `legal-zero = NOT_PROVEN`。
- PR #60 已合并：K-line technical overlays / KDJ / Alert Rules chain。
- PR #61 已合并：Screener / sector flow / northbound history chain。
- PR #59 当前仍是 UI-P2 Draft，等待独立人类视觉签字边界。

## 后续候选（均未授权）

- **P0 North Star Gap Analysis**：对照当前稳定能力，列出持仓全周期决策闭环的
  已有/复用/缺失模块，形成最小实施工作单。
- 对抗性审查发现的安全/可靠性/Foundation 项：CLI 权限边界、local API trust、
  alert-rule concurrency test harness、文档漂移、SSRF hardening 等；这些属于
  Foundation/Hardening lane，不自动覆盖产品优先级，也未授权实施。
- Engineering Reliability 后续 lint/type/coverage 等候选继续未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
