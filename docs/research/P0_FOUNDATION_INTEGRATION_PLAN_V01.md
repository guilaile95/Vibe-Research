# P0 Foundation Integration Plan v0.1

> 状态：PLAN_DRAFT（等待用户授权后执行 Merge / Retarget）
> 日期：2026-08-09
> 依据：CURRENT_DRAFT_FOUNDATION_CLOSURE 工作单；Stable = `feature/research-system-v01`

## 1. 现状基线（2026-08-09 核验）

| 项 | 值 |
| --- | --- |
| Stable branch | `feature/research-system-v01` |
| Stable head | `77bd47c855b4222e6573523f4cc5e51264ced43a` |
| PR 63（S1A bootstrap） | MERGED |

## 2. 依赖关系与建议顺序

```text
PR68 (alert-rule concurrency fix)  ──┐  独立，先合以稳定 CI 基线
PR65 (account-reality v0.1)       ──┤  独立，base=stable
PR66 (campaign-core v0.1)         ──┤  独立，base=stable
PR67 (cash-events v0.1)           ──┘  base=feat/p0-account-reality-v0.1（依赖 PR65 先合）
```

建议合并顺序：

1. **PR68 → PR65 → PR67**（PR67 依赖 PR65；PR68 修复 CI flake，先合可让 PR67 的
   Backend CI 稳定变绿）
2. **PR66** 完全独立，可与 65/67 链并行。

禁止自动 Merge / Retarget；必须逐项用户授权。PR67 若需独立合并，须先 Merge PR65，
再 Retarget PR67 base → stable 并重新跑 CI。

## 3. 各 PR 详情

| PR | 分支 | Base | Head（2026-08-09） | Mergeable | CI |
| --- | --- | --- | --- | --- | --- |
| #68 | `fix/alert-rule-concurrency-v0.1` | stable | `fa99b60…` | MERGEABLE | 运行中 |
| #65 | `feat/p0-account-reality-v0.1` | stable | `4ed0140…` | MERGEABLE | 待核验 |
| #66 | `feat/p0-campaign-core-v0.1` | stable | `1d9cb59…` | MERGEABLE | 新 head CI 运行中 |
| #67 | `feat/p0-account-cash-events-v0.1` | PR65 分支 | `f3cb78c…` | MERGEABLE | 新 head CI 运行中 |

### CI 实测（2026-08-09 12:0x UTC）

- **PR68 全部通过**：Backend tests（Linux + Windows 双平台）、Frontend build & test、
  Playwright 全套 E2E、Python Windows lock check、Whitespace —— 全部 pass。
  Alert Rule 并发修复经双平台 CI 验证，flake 消除。
- **PR66 / PR67** 新 head 的 Backend 仍失败，失败点均为 Alert Rule 并发测试
  （`test_concurrent_first_initialization` / `test_concurrent_create_different_rule_ids`，
  Round 0/1/2/4），即 PR68 修复的同一缺陷。PR66/PR67 分支不包含 PR68 修复，
  因此在 PR68 合并（或 retarget 到含修复的 base）之前无法全绿；这不构成代码问题。

## 4. 冲突分析

- PR68 只改 `backend/alert_rule_store.py`；其余 PR 均未触碰该文件 → 无冲突。
- PR65 改 `backend/app.py`（挂 account_reality_router）；PR66/PR67 未改 app.py → 无冲突。
- PR67 基于 PR65（stacked diff），依赖链内无冲突；与 PR66 无重叠文件。
- PR64（market-regime）CONFLICTING 且不在本阶段范围，保持独立，不自动解决。

## 5. Schema 兼容性

| 层 | 存储 | 变更 | 兼容性 |
| --- | --- | --- | --- |
| PR65 | 现有 `trade_ledger.sqlite3`（account_events） | 无 schema 变更，只读聚合 | 兼容 |
| PR67 | 同上（复用 account_event_store） | 新增 CASH_* 事件类型写入同一表；`validate_event_type` / `validate_persisted_cash_event` fail-closed | 兼容；旧库无 CASH_* 行也安全 |
| PR66 | 新库 `campaigns.sqlite3` | 3 表（campaigns / campaign_transitions / campaign_thesis_bindings），DDL 自带 `thesis_id UNIQUE`，schema v0.1 | 新库自动满足；旧库缺 UNIQUE → validator fail-closed，不静默迁移 |
| PR68 | 现有 alert_rules | 无 schema 变更（仅并发初始化时序修复） | 兼容 |

## 6. Router Wiring（integration 待办）

- PR65 已 wire：`app.include_router(account_reality_router.router)` → `GET /api/account/reality`。
- PR67 `MAIN_APP_ROUTER_WIRING = DEFERRED_TO_INTEGRATION`：`cash_event_router` 尚未挂主
  app；integration 时需挂载（POST/GET `/api/account/cash-events`、corrections 端点）。
- PR66 `campaign_router` 未挂主 app；integration 时需挂载（POST/GET `/api/campaigns`、
  transitions 端点）。

## 7. Migration 影响

- 无破坏性 migration。
- PR66 若检测到既有 campaigns.sqlite3 缺 `thesis_id UNIQUE`：store fail-closed，
  需要显式重建决策（导出 → 重建 → 导入校验），不得自动迁移。

## 8. Required CI（每个 PR exact-head）

- Backend tests（Linux + Windows 双平台）
- Frontend build & test
- Playwright smoke / thesis / data-health / intel-digest E2E
- Python Windows lock check
- Whitespace check

PR68 合入后，Alert Rule 并发 flake 应从 CI 消失；PR67 的 Backend CI 恢复绿色。
（已实测：PR68 双平台全绿。）

## 9. 已知停止边界

- 不自动 Merge / Ready / Retarget / Rebase / Force Push。
- 不启动 Formal Thesis（Phase 2）。
- 不启动 P0-S1B-D。
- 本计划在用户逐项授权后执行。
