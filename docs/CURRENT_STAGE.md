# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-24

This file is a **recovery pointer**, not Engineering Truth and not a second task database.

Always verify live GitHub before acting. Any SHA / Issue / PR / CI below is only a recovery hint.

## Product North Star

> Vibe-Research is a single-user, local-first A-share investment research and decision system. Its purpose is to reduce real buy / hold / sell decision errors around the user's holdings and candidates; final Formal Decision and real trading authority remain with the user.

## Current Stage

**North Star Best-Practice Product Activation / Acceleration Run**

Current state authority:

- GitHub Issue **#203** — read the **latest comment**, not the original issue body.
- At this review point: `PROJECT_FREEZE = PARTIALLY_LIFTED_FOR_THIS_RUN` for the explicitly authorized product-activation sequence.

Recovery hint for stable:

- Stable branch: `feature/research-system-v01`
- Exact stable at last review: `7be4a8bb4236bef62bf3abe6a685a35b247414b3`
- Last merged vertical: PR #210 — Watchlist Anomaly Activation

Do not trust these values without checking live GitHub.

## Immediate Work

Current active Issue:

- **#211 — P1-FH1 — StockData Fundamental Health & Cashflow Quality Activation**

Current active PR:

- **#212 — P1-FH1 — StockData Fundamental Health & Cashflow Quality**
- Last observed state: Draft / open / mergeable
- Last observed head: `dd2c98a21016128f588b30822e3a0610367dc2e2`
- Last observed CI: run `32683220657` was in progress when this file was reviewed

Current blocker:

- None confirmed from live product semantics at this review point. Resolve current PR CI / review state live before acting.

Next after current work:

- Re-read latest #203 after #212 resolves.
- If the authorized run remains open and no Stop Boundary fired, evaluate the next product vertical from the current Goal, with **Sector Market Context** as the leading recovery hint.
- Do not create a parallel implementation while #212 remains the only active product slice unless the user explicitly changes scope.

## Read First — GitHub / Repository

Read only what is needed for the current Stage:

1. `AGENTS.md`
2. `docs/CURRENT_STAGE.md`
3. GitHub Issue #203 latest comments — authorization / freeze authority
4. Current active Issue and PR, including latest comments / reviews / CI
5. `docs/PRODUCT_NORTH_STAR_V01.md`
6. `docs/ARCHITECTURE.md` only when the active change touches architecture boundaries
7. relevant source files and directly related tests

Before implementing, inspect live Open PRs. If another PR already implements the task, review or continue it instead of creating a duplicate path.

### Legacy current-state documents

The following files are retained as historical context but are **not current recovery authority**:

- `docs/PROJECT_STATE.md`
- `docs/NEXT_TASK.md`
- `docs/CHAT_HANDOFF.md`

They contain useful historical reasoning but may carry stale SHA / Stage / authorization statements. Do not use them to override live GitHub or `docs/CURRENT_STAGE.md` recovery coordinates.

## Read First — Notion

Use the connected Notion workspace only when durable product / architecture context is needed. Search these exact page titles first:

1. `Vibe-Research｜A股投资决策系统`
2. `Vibe-Research｜North Star Autonomous Run 接管｜2026-08-24`
3. `Vibe-Research｜Architecture Reality Map`

Read deeper Notion pages only when the current blocker requires them.

Notion does not override live GitHub implementation or execution state. If durable intent and live implementation disagree, report:

`Intent vs Reality conflict`

## Durable Engineering Invariants

Only genuinely durable boundaries belong here:

- **User owns formal investment authority.** AI / providers may analyze, explain, challenge or propose, but do not automatically create Formal Decision, Frozen Decision, Trade, attribution or real execution facts.
- **Provider Observation != Canonical Fact Authority.** A data provider does not become a second Holding / Trade / Decision authority.
- **Research Runtime != Canonical Fact Authority.** Fast local research paths may be used without redefining formal fact history.
- **User data and credentials stay local.** Real holdings, account data and secrets do not enter Git.
- **Reuse before infrastructure.** Do not build a second Watchlist, Sector system, Fact Lake, provider framework or equivalent authority when the existing capability can be extended.

## Current Acceptance Direction

The current product-activation stage should prove real user paths rather than API presence.

At this review point the sequence is:

1. Watchlist Anomaly — already merged via #210.
2. Fundamental Health + Cashflow Quality — active via #211 / #212.
3. Sector Market Context — candidate only after live re-evaluation and only if the current authorization still permits it.

Each vertical should close a source → backend → frontend → real user task path, then pass targeted tests, relevant regression, browser/runtime validation where applicable, independent review and current-base CI before merge.

## Deferred Scope

Unless new evidence makes one of these a blocker, do not build them as part of the current Stage:

- large BK11 rewrite or provider replacement;
- Market Heat Radar as a separate large slice;
- Market Dumps / full Research Data Plane ingestion;
- full-market Screener expansion;
- strategy / backtest lab;
- unrelated provider framework, navigation redesign, stale-PR cleanup or broad refactor.

Historical Draft PRs are context only and must not be automatically revived.

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

Then continue the highest-priority unblocked action **only when the current authorization state permits it**.
