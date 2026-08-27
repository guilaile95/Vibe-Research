# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-27

This file is a **recovery pointer**, not Engineering Truth and not a second task database.

Always verify live GitHub before acting. Any Issue / PR / state hint below is only a recovery coordinate. Do not persist an “exact current stable SHA” here; recovering Agents must resolve it and exact-head CI live.

## Product North Star

> Vibe-Research is a single-user, local-first A-share investment research and decision system. Its purpose is to reduce real buy / hold / sell decision errors around the user's holdings and candidates; final Formal Decision and real trading authority remain with the user.

## Current Stage

**TREND-RADAR1 — TrendRadar Full-Capability Sidecar Integration**

Current status:

- GitHub Issue **#228** is the active coordination authority for this integration run.
- The Owner explicitly authorized TrendRadar integration on 2026-08-27 and asked to retain essentially all useful upstream capability.
- GitHub Issue **#203** latest comment records `PROJECT_FREEZE = PARTIALLY_LIFTED_FOR_TRENDRADAR1` / `PROJECT_STATE = ACTIVE_TRENDRADAR_INTEGRATION`.
- GitHub Issue **#162 Product Reality Sprint** is paused **before Day 1**; its formal sample has not started and has not been invalidated.
- GitHub Issue **#217 GLOBAL-ACCEL2** remains CLOSED / COMPLETED.

Stable recovery coordinate:

- Stable branch: `feature/research-system-v01`
- Exact stable SHA: **resolve live; intentionally not persisted here**
- Starting stable for TREND-RADAR1 was the Product-Reality recovery baseline after PR #227; always resolve current live SHA/CI before use.

## TREND-RADAR1 Architecture Decision

TrendRadar remains a **separate local sidecar**, not copied into the Vibe repository.

Reason:

- TrendRadar is GPL-3.0;
- Vibe-Research is MIT;
- TrendRadar already owns a mature crawler / RSS / scheduler / filter / AI / translation / report / notification / storage / MCP runtime.

Target boundary:

```text
(optional self-hosted) NewsNow
            ↓
TrendRadar Core sidecar
crawler / RSS / scheduler / filter / AI / translation / reports / notifications
            ↓ TrendRadar-owned local/remote storage
TrendRadar MCP sidecar
            ↓ local HTTP/MCP
Vibe TrendRadar Gateway
            ↓
Attention / Public-Opinion Observation Plane
            ↓
Intel / Watchlist / StockData / Discovery / Candidate Research / Daily Review
```

Do **not** vendor/copy/import TrendRadar GPL source into Vibe and do not reimplement its entire runtime merely to make it look native.

## Authority Boundary

TrendRadar provides **research observations / attention context**, not formal investment authority.

It may provide:

- hotlist / RSS observations;
- rank history, first/last seen, crawl count and attention acceleration;
- keyword / AI-filter metadata;
- trend/lifecycle/viral/sentiment analysis;
- article-read results;
- report, scheduler, storage and notification status.

It must not directly create or mutate:

- Holding;
- Current/Formal Thesis;
- Formal Decision;
- Frozen Decision;
- Trade;
- Trade Attribution;
- BUY/SELL actions.

TrendRadar AI relevance, sentiment or hotness means “worth attention/research”, never “worth buying”.

## #228 Execution Direction

The integration is a multi-keeper global run. Do not stop after a single Intel card.

### Phase 0 — Upstream Qualification / Sidecar Bootstrap

- pin an exact qualified TrendRadar runtime/image rather than durable `latest`;
- run TrendRadar Core and MCP as separate local-only services;
- keep config/output/secrets outside Git;
- qualify crawl, RSS, SQLite/storage, report server, current MCP tools/resources, scheduler, AI-disabled behavior, notification-disabled behavior;
- preserve self-hosted NewsNow as the long-term local-first target option.

### Phase 1 — Vibe Gateway + Intel

Build a strict Vibe-owned gateway over the local TrendRadar boundary and expose the useful query/analysis surface in the existing `/intel` product area.

Failure must be explicit `UNAVAILABLE`; do not silently substitute Investment News and label it TrendRadar.

### Phase 2 — Investment Research Context

Connect public-attention observations into existing:

- Intel;
- Watchlist;
- StockData;
- Full Market / Discovery;
- Candidate Research;
- Daily Review / AI context.

Reuse existing Evidence/Note authority for any user-explicit promotion; never auto-promote TrendRadar observations into Formal Decision facts.

### Phase 3 — Full Upstream Capability Retention

Keep TrendRadar as execution owner for:

- keyword / AI filtering;
- AI analysis;
- AI translation;
- scheduler;
- reports;
- local/remote storage;
- notification fanout;
- MCP analysis and article reader.

Vibe may provide status/readback and explicit user-triggered actions. Automated tests must use fake/local notification capture and must not message real people.

### Phase 4 — Operational Convenience

Provide sidecar health/version/config-location/report/storage diagnostics. Prefer TrendRadar's own visual configuration editor/operator flow instead of duplicating every YAML field in Vibe. Add narrow local config management only if later evidence proves it necessary.

## Existing Vibe Capability to Reuse

- `/intel` already has Investment News + Vibe AI Digest; TrendRadar must not become a second generic RSS page.
- Watchlist already has anomaly product surface.
- `/stock-data?code=...` already supports research continuation.
- Candidate Research / PRE-ENTRY already exists.
- Full Market / Screener v0.1 already exists.
- Vibe AlertRule currently owns CRUD only and explicitly does not own runtime evaluation/notification/scheduling/history; do not make TrendRadar a second AlertRule authority.

## Privacy / Secrets

Never put in Git or logs:

- AI API keys;
- notification webhook URLs/tokens;
- Telegram credentials;
- SMTP passwords;
- S3 credentials;
- private feed credentials;
- real holdings/account/trade/private Thesis data.

TrendRadar runtime config/output/secrets stay local/private.

## Product Reality #162

`PRX1` is paused before formal Day 1 while #228 is active.

Do not collect or claim formal 10-trading-day Product Reality observations against a moving TrendRadar integration baseline.

After #228 closes:

1. resolve new stable/exact-head CI;
2. re-establish Product Reality baseline;
3. re-run readiness smoke if core user paths materially changed;
4. set #162 READY again;
5. only then may formal Day 1 start.

## Immediate Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve live `feature/research-system-v01` SHA and exact-head CI.
3. Read **#203 latest comment** for authorization state.
4. Read **#228** and its latest comments for TREND-RADAR1 progress / keeper boundaries.
5. Read **#162 latest comments** to confirm Product Reality remains paused before Day 1 while #228 is active.
6. Inspect current Open / Draft PRs to avoid duplicate work; historical Draft PRs are context only.
7. Read only source/tests needed for the current #228 keeper.
8. Use the named Notion research page below for durable TrendRadar architecture context.

## Read First — GitHub

1. `AGENTS.md`
2. `docs/CURRENT_STAGE.md`
3. Issue #203 latest comment
4. Issue #228 latest comments
5. live stable / exact-head CI
6. Issue #162 latest comment when Product Reality sequencing matters

## Read First — Notion

Search these exact page titles first when durable context is needed:

1. `Vibe-Research｜A股投资决策系统`
2. `TrendRadar × Vibe-Research｜全能力接入调研与架构决策｜2026-08-27`
3. `Vibe-Research｜GLOBAL-ACCEL2 全面推进｜2026-08-25`
4. `Vibe-Research｜North Star Autonomous Run 接管｜2026-08-24`
5. `Vibe-Research｜Architecture Reality Map`

Notion does not override live GitHub implementation/execution state.

## Known Nonblocking Follow-Up

- #220 remains open for real Market Dump operational completeness beyond Full Market v0.1. It is not automatically active during TREND-RADAR1 unless required by the integration.
- #169 remains a historical/read-only audit asset. Do not restart the entire audit unless a current TrendRadar keeper creates a validated authority/correctness concern.

## Legacy Current-State Documents

These are historical context, not current recovery authority:

- `docs/PROJECT_STATE.md`
- `docs/NEXT_TASK.md`
- `docs/CHAT_HANDOFF.md`

## Durable Engineering Invariants

- **User owns formal investment authority.** AI/providers may analyze, explain, challenge or draft, but do not automatically create Formal Decision, Frozen Decision, Trade, Attribution or real execution facts.
- **Provider/attention Observation != Canonical Fact Authority.**
- **Research Runtime != Canonical Fact Authority.**
- **GPL sidecar != Vibe source tree.** Interact across a process/data boundary; do not copy its implementation into the MIT repository.
- **User data and credentials stay local/private.**
- **Reuse before infrastructure.** Extend existing Intel/Watchlist/StockData/Discovery/Candidate paths before creating competing product surfaces.

## Current Acceptance Direction

TREND-RADAR1 completes only when Issue #228's Global Completion Target is honestly re-evaluated, including upstream capability retention, Vibe integration surfaces, licensing/authority/secrets boundaries, no active keeper PRs, stable exact-head CI, recovery-coordinate sync and Notion handoff.

Do not manufacture completion by silently omitting blocked upstream features; record concrete `BLOCKED` evidence instead.

## Deferred / Escalation Boundary

Do not autonomously cross:

- destructive/irreversible user-data migration;
- broker/order/automatic trading execution;
- real external notification/message during automated validation;
- new paid account/service or material recurring cost;
- credential/account-security changes;
- unresolved conflict between two plausible Formal Authorities;
- irreversible real-user holding/trade mutation without explicit user action.

## Recovery Output

Return once at new-session / handover recovery:

```text
CURRENT ENGINEERING STATE

STABLE_BRANCH:
EXACT_STABLE_SHA:
AUTHORIZATION_STATE:
STATE_AUTHORITY:
CURRENT_STAGE:
ACTIVE_ISSUE:
ACTIVE_PR / HEAD:
LOCAL_WORKSPACE:
CI:
CURRENT_BLOCKER:
BLOCKING_DEFECTS:
PRODUCT_REALITY_BLOCKERS:
DEFERRED_SCOPE:
SOURCE_CONFLICTS:
NEXT_ACTION:
```

Then follow #203 + #228. While #228 is active, do not revert to Product Reality observation just because #162 remains open.