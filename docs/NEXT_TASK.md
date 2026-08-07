# 当前下一任务

本文件是**唯一当前授权任务**的载体；产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**Project Governance Consolidation v0.1**（治理收口，非产品任务）

- 分支：`chore/project-governance-v0.1`（自稳定 Head `cd17fec2` 创建）
- 目标：Git/GitHub 治理、权威状态文档、开发门禁收口；PR #43 只做
  Recovery Assessment（推荐从稳定 Head 建 recovery 分支迁移有效改动，
  见 `docs/GOVERNANCE.md` §6）
- 停止点：本阶段完成后停止，等待下一次明确授权；不处理 BK-11 / SQ-02B /
  PR #47 / PR #43 修改。

**已授权产品开发任务：无。**

## 最近完成

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

- **PR43 Recovery v0.1**（建议下一阶段）：从稳定 Head `cd17fec2` 建
  `feat/intel-daily-digest-v0.1-recovery`，cherry-pick PR #43 的 4 个提交
  （`64c5b59` → `4c8f97e` → `c2f7af4` → `0730f4b`），解 2 处机械冲突
  （`backend/app.py`、`frontend/package.json`）后开新 PR。待本阶段完成后授权。
- BK-11：已暂停（Issue #48），恢复需新授权。
- BK-01 ~ BK-10 其余候选：见 `docs/PRODUCT_BACKLOG.md`，均未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
