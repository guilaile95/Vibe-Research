# Account Bootstrap Product Activation v0.1

## 定位

让一个真实、尚未初始化的用户账户，通过已有 canonical bootstrap authority
安全录入当前持仓，然后真实 `GET /api/decision-inbox` 可以看到这些持仓。

```text
Empty Account
→ POST /api/position/bootstrap-preview（零写）
→ POST /api/position/bootstrap-commit（原子写）
→ GET /api/position/derived
→ GET /api/holdings/campaign-composition
→ GET /api/decision-inbox
```

本任务**不新建任何 bootstrap authority**：domain authority
（`position_reality_service.bootstrap_preview / bootstrap_commit` +
`account_event_store.atomic_bootstrap`）与 HTTP API
（`POST /api/position/bootstrap-preview` / `bootstrap-commit`）均复用 stable
既有实现，仅补齐跨层 E2E 验收证明与产品语义文档。

## 冻结语义

```text
ACCOUNT_BOOTSTRAP_ROLE = INITIAL_CURRENT_ACCOUNT_STATE_CAPTURE

LEGACY_POSITION_OPENING != BUY
origin = PRE_VIBE
historical_trades = UNKNOWN
provenance = MANUAL
acquired_before_vibe = 1

PRE_VIBE_HISTORY = UNKNOWN
HISTORICAL_TRADE_RECONSTRUCTION = NO
FIFO_INFERENCE = NO
AI = NO

AUTO_CAMPAIGN_CREATION = NO
AUTO_THESIS_CREATION = NO
AUTO_FORMAL_DECISION_CREATION = NO
```

账户初始化与 Campaign 建立是两个独立用户动作。Bootstrap 完成后没有
Campaign 的持仓保持：

```text
UNASSIGNED_HOLDING → SETUP_REQUIRED → CREATE_CAMPAIGN
```

## 允许输入（复用既有 payload contract）

```json
{
  "ledger_start_at": "2026-08-01",
  "opening_cash": 100000.0,
  "positions": [
    {"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 1500.0}
  ],
  "note": "可选"
}
```

`cost_basis` 为每股成本语义（对齐 portfolio.json 的 cost）；推导结果中的
`cost_basis` 为期初总成本（每股 × 股数）、`avg_cost` 为每股成本。未知成本
保持 `None` / `cost_known=false`。

禁止无 authority 的字段：`historical_buy_date`、`historical_buy_price`、
`historical_trade_id`、`historical_order_id`、broker execution history。

## 安全属性

- Preview：零写（不创建库、不写事件）。
- Commit：`atomic_bootstrap` 单事务原子写；空账户才允许；已有账户事件或
  post-Vibe 交易 → 409 拒绝；重复 bootstrap → 409；partial write 不可能。
- 禁止 force / overwrite / replace / reset；历史修正必须走正式 correction
  authority。
- 输入严格校验：未知顶层/持仓字段、重复代码、非法代码、shares ≤ 0 或 bool、
  cost NaN/inf/负 全部 422 fail closed。

## Preview 语义展示要求

Preview 响应必须让用户理解“这是开始使用 Vibe 时的当前持仓快照，不是历史
BUY 交易”：

```text
event_type = LEGACY_POSITION_OPENING
origin = PRE_VIBE
historical_trades = UNKNOWN
provenance = MANUAL
```

## E2E 验收（隔离环境，已固化测试）

`backend/tests/test_p0_account_bootstrap_activation.py` 覆盖：

- preview 零写 + 冻结语义字段；
- commit → derive 精确（shares / cost / UNKNOWN 保持）；
- composition：无 Campaign → 全部 `UNASSIGNED_HOLDING`；
- decision inbox：同一批持仓全部出现、`SETUP_REQUIRED`、
  `CREATE_CAMPAIGN`、无 phantom / fake BUY / duplicate / missing；
- 重复 bootstrap / 已有事件 / 已有 post-Vibe 交易 → 409；
- 全部非法输入 → 422 且零写。

## 真实用户边界

允许只读检查与 preview；`bootstrap_commit` 属于真实投资账户数据写入，
必须由用户显式确认后执行，Agent 不代为写入。

## 边界

不在本任务范围：price reason_codes、CDA1B 集成、financial report-period
applicability、market_sector / disclosures adapter、Hard Risk、Material
Change、Campaign/Thesis/Formal Decision auto-create、broker import/sync、
历史交易重建、portfolio redesign。
