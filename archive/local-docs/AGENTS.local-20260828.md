# Vibe-Research Execution Rules

## 1. Source of Truth

不同问题使用不同权威来源：

- 代码、Branch、SHA、PR、CI 等实现事实：以现场 Git / GitHub / repository state 为准。
- 项目总体状态：`docs/PROJECT_STATE.md`
- 产品方向：`docs/PRODUCT_NORTH_STAR_V01.md`
- 当前授权：用户当前明确指令 > `docs/NEXT_TASK.md`
- 执行纪律：本文件 `AGENTS.md`

旧报告、交接文档、backlog 只能作为证据，不能覆盖当前权威来源。

同一种状态只维护一个权威位置。

---

## 2. Task Mode

任务分两类：

### READ_ONLY
Review / Audit / Gap Analysis / Research 默认只允许读取、核验、分析和报告。

不得修改文件、创建分支、commit、push、修改 PR，除非明确授权。

### IMPLEMENTATION
用户明确授权具体实现任务后，默认允许在该任务范围内：

- 创建任务分支；
- 修改必要代码、测试和最小必要文档；
- 运行验证；
- 普通 commit；
- push 任务分支；
- 创建或更新 Draft PR；
- 修复本任务直接引入的问题。

始终需要单独授权：

- 修改或 push stable；
- PR 转 Ready；
- Merge；
- force push / history rewrite；
- destructive cleanup；
- 开始新的产品 Slice。

---

## 3. Scope Control

只完成当前授权范围。

可以自动修复：

- 本任务引入的 regression；
- 本任务 acceptance criteria 未满足的问题；
- 本任务代码路径内的阻断问题。

以下默认只记录，不自动处理：

- pre-existing failure；
- unrelated flaky test；
- 其他 Slice；
- unrelated security / hardening；
- repo-wide refactor；
- “顺手优化”。

完成当前 Slice 后立即 STOP。

---

## 4. Build in Layers

始终从最小可工作的端到端版本开始，再逐层增加能力。

> Never trade a working product for unfinished complexity.

每个 Slice 应尽量独立：

- 可测试；
- 可审查；
- 可回滚；
- 可单独合并。

不要一次性重写整个系统。

---

## 5. Simplicity and Long-Term Design

选择满足当前需求的最简单正确实现。

避免：

- speculative abstraction；
- speculative config；
- unnecessary indirection；
- future-proof schema；
- 尚未授权 Slice 的字段预埋；
- 临时错误模型。

长期设计不等于提前实现未来需求。

正确目标是：

> 当前实现本身长期正确，同时只实现当前需要的最小能力。

---

## 6. Reuse, DRY and Modularity

修改前先判断：

`REUSE / EXTEND / REPLACE`

不要因为名字不同就重复开发已有正确能力，也不要因为名字相似就强行复用错误抽象。

DRY 要求：

- 同一业务逻辑只保留一个实现；
- 同一状态只保留一个权威来源；
- 重复逻辑有明确复用价值后再提取；
- 不为未来可能需求提前抽象。

保持 storage / domain / service / API / deterministic policy / AI / UI 职责分离。

---

## 7. Compatibility Policy

内部废弃实现确认无消费者后，可以删除，不要无限增加 compatibility layer 或 fallback。

但必须保护：

- 用户真实持仓和账户数据；
- Trade Ledger；
- Evidence / Thesis 历史；
- Frozen Decision；
- 已有本地数据库；
- 正式 UI 正在使用的稳定契约。

涉及真实用户数据时：

- 不允许 silent overwrite；
- 不允许 destructive reset；
- 不允许伪造历史；
- 无法可靠解释时保持 UNKNOWN；
- migration 必须显式且可验证。

---

## 8. Deterministic / AI Boundary

Vibe-Research 是 deterministic-first 系统。

确定性层负责：

- facts；
- validation；
- freshness；
- account mechanics；
- hard risk；
- state transition；
- action envelope。

AI 负责：

- reasoning；
- explanation；
- challenge；
- synthesis；
- proposal。

AI 不得绕过 Hard Risk、修改事实、把 UNKNOWN 变成事实、自动修改 Original Thesis、自动创建 Formal Decision 或自动交易。

---

## 9. Fail Closed and User Data

涉及高价值事实时必须 fail closed。

例如：

- corrupted ledger；
- impossible position；
- invalid migration；
- critical evidence conflict；
- stale decision；
- unknown eligibility。

UNKNOWN 必须保持 UNKNOWN。

真实：

- portfolio；
- account；
- trade history；
- private notes；
- credentials；

不得进入 Git。

自动化测试必须使用 tmp / fixture / fake data，不得写入用户真实数据文件。

API Key / Token 不得写入源码、Git、日志、测试快照或 browser localStorage。

---

## 10. Git Safety

禁止未经明确授权执行任何可能丢失工作或重写历史的操作，包括：

- `git branch -D`
- `git clean`
- `git reset`
- destructive `git restore`
- `git checkout -- <path>`
- force push

不得对已 push 的提交 amend / rebase / squash history。

修正使用新的普通 commit。

不得直接修改或 push stable。

---

## 11. Validation

测试验证真实契约，不为 CI 变绿而改弱测试。

不得：

- 删除失败测试；
- 弱化断言；
- 把 static check 写成 runtime PASS；
- 把专项测试写成 full regression。

必须区分：

- LOCAL
- EXACT_HEAD_CI
- BROWSER_RUNTIME
- LIVE_EXTERNAL_DATA

未运行就明确写 `NOT_RUN` / `NOT_COMPLETED`。

---

## 12. Reporting

完成报告只包含：

- Stable Base SHA
- Task Branch
- Final Head SHA
- 实际改动
- 实际测试
- exact-head CI
- 与计划偏差
- remaining blockers
- Draft PR
- final status
- stop boundary

不要重复整份设计和任务说明。

核心原则：

> Build the smallest correct end-to-end system, keep it working, and grow it one validated layer at a time.
