# 当前下一任务

本文件是**唯一当前授权任务**的载体；产品候选池见
[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)，项目总体状态见
[`docs/PROJECT_STATE.md`](PROJECT_STATE.md)，治理契约见
[`docs/GOVERNANCE.md`](GOVERNANCE.md)。

## 当前已授权任务

**Engineering Reliability Baseline v0.1 — Phase A Qualification**（工程审计，
非产品任务；只测量不改造）

- 分支：`audit/engineering-reliability-baseline-v0.1`（自稳定 Head `060b5d0` 创建）
- 范围：Python 依赖可复现性 / 前端依赖 audit / Actions 供应链 / CI 可靠性 /
  静态质量基线 / 密钥扫描 / 干净复现实验（REL-01 ~ REL-07）
- 状态：`MEASUREMENT_COMPLETE / IMPLEMENTATION_PENDING`（Phase A 完成，
  Phase B 实现未授权；结果见 `docs/research/ENGINEERING_RELIABILITY_BASELINE_V01.md`）
- 停止点：本阶段完成后停止；不升级依赖、不修 flake、不加 CI 门控。

**已授权产品开发任务：无。**

## 最近完成

- 工程可靠性基线 Phase A（2026-08-08）：七项测量完成，债务矩阵见
  `docs/research/ENGINEERING_RELIABILITY_BASELINE_V01.md`（无 P0/P1 泄漏，
  Python 依赖锁为最高优先 P1 债）。
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

- Engineering Reliability Implementation v0.1（Phase B，待授权）：依赖锁 →
  Actions 升级 → ruff 基线 → mypy 分文件 → 测试竞态修复；thesis E2E 稳定性
  另立专项。
- thesis E2E 稳定性加固（已实测 intermittent failure，P2 债务，非授权任务）。
- Intel Digest saving 请求显式 timeout（P2 候选，非授权任务）。
- BK-11：已暂停（Issue #48），恢复需新授权。
- BK-01 ~ BK-10 其余候选：见 `docs/PRODUCT_BACKLOG.md`，均未授权。

## 本地目录边界

本文件不维护瞬时 worktree/备份清单。历史本地目录只有在可访问 Windows
文件系统并完成现场核验后才允许清理；远端开发不因此阻塞。
