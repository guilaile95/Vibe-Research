# 当前下一任务

本文件是**唯一当前授权任务**的载体；产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**PR43 Recovery v0.1**（Intel Daily Digest 功能迁移，产品功能恢复）

- 分支：`feat/intel-daily-digest-v0.1-recovery`（自稳定 Head `77a7ace` 创建）
- 目标：将旧 PR #43 "Intel Daily Digest v0.1" 的有效功能迁移到当前最新稳定
  基线；cherry-pick `64c5b59 → 4c8f97e → c2f7af4 → 0730f4b`，解
  `backend/app.py` / `frontend/package.json` 冲突，完整验证后本地提交
- 状态：`RECOVERY_IMPLEMENTED / LOCAL_VERIFIED / NOT_MERGED`
  （尚未 push、未创建新 PR、旧 PR #43 未关闭）
- 停止点：本阶段完成后停止，等待下一次明确授权（push + Draft PR）；
  不处理 BK-11 / SQ-02B / PR #47 / Issue #48。

**已授权产品开发任务：无。**

## 最近完成

- PR43 Recovery v0.1：4 提交迁移完成、冲突解决、验证进行中（2026-08-07）。
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

- **PR43 Recovery 后续（push + 新 Draft PR）**：待本轮验证与独立审查通过后
  另行授权；旧 PR #43 的关闭与否亦待授权。
- BK-11：已暂停（Issue #48），恢复需新授权。
- BK-01 ~ BK-10 其余候选：见 `docs/PRODUCT_BACKLOG.md`，均未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
