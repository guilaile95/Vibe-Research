# 当前下一任务

本文件是**唯一当前授权任务**的载体；产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**BK-11 Zero-Cost Source Research Recovery & Publication v0.1**

- 范围：`research closure / validation / independent review / Draft PR only`；
- 状态：已授权；从 B1/B2 后的新稳定基线恢复冻结研究证据，完成离线验证、
  小样本 live smoke、独立复审与 Draft PR 发布；
- 停止点：Draft PR 与 CI 状态形成后停止，不转 Ready、不合并；
- 不授权：`production ingestion / scheduler / backfill / Slice 4`，也不处理
  PR #47、Tushare Token、生产 BaoStock 接入或其它 BK-11 实施。

**已授权产品开发任务：无。**

## 最近完成

- `B1_DEPENDENCY_REPRODUCIBILITY = CLOSED`：PR #52 已合并（Merge `fd7cdaa`），
  Linux/Python 3.11 与 Windows/Python 3.12 authority lock、canonical lock check
  和双平台离线测试进入稳定分支。
- `B2_ACTIONS_MODERNIZATION = CLOSED`：PR #53 已合并（Merge `2316ba6`），
  当前 CI 使用 `actions/checkout@v7`、`actions/setup-python@v6`、
  `actions/setup-node@v6`。
- Engineering Reliability Baseline Phase A（2026-08-08）：七项测量完成，
  债务矩阵见 `docs/research/ENGINEERING_RELIABILITY_BASELINE_V01.md`。
- Intel Daily Digest recovery 全流程收口（2026-08-07）：PR43 Recovery v0.1
  （4 提交 cherry-pick + 冲突解决 + 全量验证）→ PR43 Recovery Publication
  （push + Draft PR #50 + CI 7/7 + 远端独立审查 PASS + 旧 PR #43 关闭）→
  PR #50 已合并（Merge `1339f7a`，Intel Digest 正式进入稳定分支）。
- 治理状态同步（本分支）：权威文档更新为 PR #50 合并后事实（PROJECT_STATE /
  NEXT_TASK / GOVERNANCE / KNOWN_ISSUES / ARCHITECTURE）。
- GOV-05：治理 PR #49 已合并（Merge `77a7ace`），治理契约进入稳定分支。
- Project Governance Consolidation v0.1：建立唯一状态权威链、修正文档冲突、
  CI 分级与分支保护策略、PR #43 Recovery 评估（2026-08-07，本地提交）。
- BK-11 暂停/归档（Issue #48，2026-08-06）：冻结一切 BK-11 开发授权。
- BK-11 production input source audit（PR #46，Merge `cd17fec2`，BLOCKED）。
- BK-11 history integration for Daily Review（PR #45，Merge `12593c3`）。
- BK-11 pure compute chain（PR #44，Merge `17c7f1d`）。
- shadow-mode top risk analysis（PR #42，Merge `6da75b9`）。
- 技术指标与价格触发（PR #41，Merge `ad84474`）。
- BK-03 切片 2 北向资金权威数据契约（PR #40，Merge `40d0dba`）。

## 后续已登记候选

- Engineering Reliability Phase B3（未授权）：ruff 基线、mypy 分文件与 ESLint；
  不因 B1/B2 关闭而自动开始。
- thesis E2E 稳定性加固（已实测 intermittent failure，P2 债务，非授权任务）。
- Intel Digest saving 请求显式 timeout（P2 候选，非授权任务）。
- BK-11 生产接入、调度、回填与 Slice 4 继续暂停；本轮仅恢复 zero-cost
  research closure/publication。
- BK-01 ~ BK-10 其余候选：见 `docs/PRODUCT_BACKLOG.md`，均未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
