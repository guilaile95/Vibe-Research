# Decision Inbox Runtime v0.1

## 定位

`GET /api/decision-inbox` 是 current-only 只读 read model：

```text
canonical open holding（#118 composition snapshot，不重读）
  → 每个真实 ACTIVE / REDUCING Campaign
  → DDA1 strategy dependency definition
  → capability results
       ├─ cap.security.price_reference → #116 adapter（readonly Fact Lake）
       └─ market_sector / disclosures / financials → NOT_EVALUATED（暂无 adapter）
  → CCD1 campaign critical data
  → RA1 decision assurance coverage
  → DI1 CampaignFacts → project_campaign
```

没有 current Campaign 的 OPEN holding 生成 holding-grain `UNASSIGNED_HOLDING`
setup item，绝不伪造 campaign_id / strategy / campaign_status。

## 诚实边界（本版本不允许 false clean）

- Hard Risk / Material Change 无授权 authority：恒 `NOT_EVALUATED`。
- Formal Thesis / Frozen Decision 仅以 current-only 结构事实读取；
  RA1 的 FORMAL_THESIS / FORMAL_DECISION 维度无 same-as-of 适用性 authority，
  保持 `NOT_EVALUATED`（读取过记录 ≠ 完成评估）。
- price 可用绝不使整个 Campaign 变成 `USABLE` / `EVALUATED`；
  任一 required capability 未评估 → CCD `(UNKNOWN, NOT_EVALUATED)`。
- `coverage_complete` 只可能为 False（本版本无任何维度可证明已评估）。
- 因此 campaign item 只会投影为 `SETUP_REQUIRED` / `REVIEW_REQUIRED` /
  `BLOCKED_BY_DATA`，不会出现 `NO_ACTION_REQUIRED`。

## 时间语义

- 一次请求 = 一个 `as_of`（默认当前 UTC 快照；测试可注入）。
- 同一 `as_of` 逐字贯穿 DDA → capability results → CCD → RA → DI1。
- 不做历史回放、不做 PIT；`fetched_at` / `committed_at` 不改变评估时点。
- Frozen Decision 只选 `committed_at <= as_of` 的最新一条。

## 零写入

runtime 只调用既有只读 authorities：

- `holdings_campaign_composition.assemble_holdings_campaign_composition`
- `critical_data_dependency_policy.resolve_strategy_dependencies`
- `critical_data_price_reference_adapter.evaluate_price_reference_capability`
- `formal_thesis_projection.project_current_thesis`
- `frozen_decision_service.list_decisions`
- Fact Lake：仅 `open_existing_fact_lake(readonly=True)`；
  未配置 `VR_FACT_LAKE_ROOT` 或根不存在 → price capability 为 `NOT_EVALUATED`。

禁止：创建 Campaign / Thesis / binding、写入决策或快照、market refresh、
portfolio fallback、任何 auto-create。

## Fail closed

- composition 非 canonical → `200 + NOT_EVALUATED`，不读取任何 Campaign 权威。
- authority 数据损坏 / identity / as_of 不一致 → typed integrity error → `500`。
- HTTP 错误均为固定脱敏文案，不暴露路径 / SQL / traceback。

## 输出 envelope

```json
{
  "schema_version": "decision_inbox_runtime.v0.1",
  "as_of": "...",
  "evaluation_status": "EVALUATED | NOT_EVALUATED",
  "canonical": true,
  "reason_codes": [],
  "holding_setup_items": [],
  "campaign_items": [],
  "total_holdings": 0,
  "total_campaign_items": 0
}
```

`campaign_items[*]` 为 `decision_inbox_projection.InboxItem.to_dict()`；
`holding_setup_items[*]` 为 `UNASSIGNED_HOLDING` 产品节点，与 DI1 分离。
