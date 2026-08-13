# Campaign Setup Product Activation v0.1（P0-CS1）

## 定位

关闭真实用户路径：

```text
真实 OPEN holding（无 ACTIVE/REDUCING Campaign）
  → composition: UNASSIGNED_HOLDING
  → inbox: SETUP_REQUIRED → CREATE_CAMPAIGN
  → 用户显式 POST /api/campaigns（security_code + strategy）
  → DRAFT Campaign（campaign_id 服务端生成）
  → 用户显式逐级 transition：DRAFT → RESEARCHING → PRE-ENTRY → ACTIVE
  → composition 识别 current Campaign
  → inbox 从 holding setup item 切换为真实 campaign item
```

本 Slice 只激活「创建 + 显式 lifecycle」产品路径；
Thesis / Formal Decision / Hard Risk / Material Change 等下游 authority
保持既有诚实边界，不伪造、不自动创建。

## 关键声明

| 声明 | 值 |
| --- | --- |
| CAMPAIGN_SETUP_ROLE | EXPLICIT_USER_CAMPAIGN_IDENTITY_AND_LIFECYCLE |
| CREATE_STATUS | DRAFT |
| STRATEGY_MUTABLE | NO |
| AUTO_ACTIVATION | NO |
| AUTO_THESIS | NO |
| AUTO_FORMAL_DECISION | NO |
| MULTI_CAMPAIGN_PER_SECURITY | YES |
| CAMPAIGN_ALLOCATION_INFERENCE | NO |
| AI | NO |

- 创建输入只有 `security_code` + `strategy`（SHORT/SWING/MEDIUM 精确枚举，
  无 silent normalization）；`status` / `campaign_id` / `created_at` 由服务端
  决定（router 输入模型 `extra="forbid"` 拒绝客户端提交）。
- 同一 security_code 允许多个 Campaign，身份由 `campaign_id` 决定；
  无 UNIQUE(security_code) / UNIQUE(security_code, strategy)；
  都 ACTIVE 时 composition 保留全部真实 Campaign，不 invent allocation
  （campaign-level capital allocation 继续 UNKNOWN）。

## Frozen Lifecycle Graph（复用，未扩展）

```text
DRAFT → RESEARCHING → PRE-ENTRY → ACTIVE → REDUCING → CLOSED
DRAFT / RESEARCHING / PRE-ENTRY → REJECTED / EXPIRED
CLOSED / REJECTED / EXPIRED = TERMINAL
```

transition 必须显式（CAS：`expected_status` + `to_status`），
非法边 / same-state / wrong expected_status → 409，状态不变。
本 Slice 未修改 graph；后端 `campaign_store._TRANSITION_GRAPH` 是唯一权威。

## Current Membership 语义（未修改 #118）

- `CURRENT_CAMPAIGN_STATUSES = {ACTIVE, REDUCING}`：
  DRAFT / RESEARCHING / PRE-ENTRY 不属于 current Campaign membership，
  composition 继续诚实输出 `UNASSIGNED_HOLDING`，不伪造已解决。
- 只有 Campaign 进入 ACTIVE 后，composition 才识别为 current Campaign，
  inbox 才投影 campaign item（并停止输出同一 holding 的 setup item）。

## 本 Slice 新增

1. **只读 read-model `GET /api/campaigns/{campaign_id}/next-actions`**
   （`campaign_router.get_campaign_next_actions`）：
   派生自 frozen graph 单一权威（`campaign_store.next_actions`），
   响应自包含 campaign 身份 / status / next_actions（terminal → 空）。
   新增理由：前端必须展示「下一合法动作」，
   而现有 4 个 campaign API 均不含该派生信息；前端不得复制 graph。
   动作执行仍走正式 `POST .../transitions`（CAS + graph 校验）。

2. **完整产品链 E2E 矩阵测试**（`tests/test_campaign_setup_product_e2e.py`）：
   真实 isolated temp DB 上证明 §8 A–F 全矩阵、§9 非法 transition 拒绝 +
   status unchanged、§10 同 Security 多 Campaign、no auto thesis / formal
   decision / activation。

3. **Frontend Decision Inbox 页面**（`/decision-inbox`，nav「决策待办」）：
   - UNASSIGNED_HOLDING 行 → 「创建 Campaign」→ 表单（security_code 固定
     自 holding、strategy 三选必选、显式确认「创建后状态为 DRAFT，
     不会自动激活」）→ POST /api/campaigns → 显示 campaign_id / strategy /
     status=DRAFT。
   - campaign 行：真实 status / strategy / campaign_id + 「下一合法动作」
     按钮（来自 next-actions API；每步显式点击，无「立即激活」链式按钮）。
   - API 失败（含 409）如实显示 backend detail，绝不伪装成功；
     刷新只从 backend 拉取，不保留本地伪造状态。
   - 前端纯逻辑集中在 `src/lib/decisionInbox.ts`（payload 形状 + 文案），
     不定义 transition graph。

## 诚实边界（未改变）

- ACTIVE Campaign 无 Formal Thesis / Frozen Decision / Hard Risk /
  Material Change authority 时，inbox campaign item 只投影为
  `SETUP_REQUIRED` / `REVIEW_THESIS` / `BLOCKED_BY_DATA` 等诚实状态，
  绝不出现 `NO_ACTION_REQUIRED` false clean（E2E 测试锁定）。
- 创建 / transition 不自动创建 Thesis、Formal Decision，
  不自动推进 lifecycle（AUTO_THESIS_CREATION = NO 等已在 E2E 断言）。

## 非目标

transition graph 扩展、自动 ACTIVE、自动 Strategy 推断、AI 推荐 authority、
auto Thesis、auto Formal Decision、Campaign allocation 推断、
price reason_codes、CDA1B、financial applicability、Hard Risk、
Material Change、market_sector、disclosures、Sell Engine、TCR1、TB2、SEC3、
broker import、真实账户写入。
