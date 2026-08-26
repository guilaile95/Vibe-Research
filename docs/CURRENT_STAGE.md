# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-26

This file is a **recovery pointer**, not Engineering Truth and not a second task database.

Always verify live GitHub before acting. Any Issue / PR / state hint below is only a recovery coordinate.

## Maintenance Rule

Update this file only when recovery coordinates materially change, for example:

- current Stage changes;
- the authorization / freeze authority changes;
- the leading coordination Issue or active keeper PR changes;
- a completed workstream changes what the next recovering Agent should inspect;
- the named repo / Notion read-first pointers change;
- a genuinely durable invariant changes.

Do **not** update it for every commit, CI run, test result, temporary worktree or minor implementation detail. If this file becomes stale, live GitHub wins and the recovering Agent should report the conflict rather than asking the user to reconstruct history.

Do not store an “exact current stable SHA” here. Recovering Agents must resolve `EXACT_STABLE_SHA` and exact-head CI from live GitHub.

## Product North Star

> Vibe-Research is a single-user, local-first A-share investment research and decision system. Its purpose is to reduce real buy / hold / sell decision errors around the user's holdings and candidates; final Formal Decision and real trading authority remain with the user.

## Current Stage

**PRX1 — Product Reality Sprint / Formal 10-Trading-Day Real-Use Observation**

Current status:

- GitHub Issue **#162 — Product Reality Sprint** is the next product-truth authority.
- `STATE = READY_FOR_FORMAL_10_TRADING_DAY_OBSERVATION`.
- The formal sample has **not started automatically**; do not invent Day 1 or synthetic real-use evidence.
- GitHub Issue **#217 GLOBAL-ACCEL2** is **CLOSED / COMPLETED** after its Final Closure Gate passed.
- GitHub Issue **#203** latest comment is the authorization / freeze authority and currently records `PROJECT_FREEZE = RESTORED` / `PROJECT_STATE = FROZEN`.

Stable recovery coordinate:

- Stable branch: `feature/research-system-v01`
- Exact stable SHA: **resolve live; intentionally not persisted here**
- GLOBAL-ACCEL2 final runtime baseline before this recovery-coordinate update was the stable containing merged PRs #224 Campaign AI Draft, #225 Candidate Research and #226 Full Market Discovery v0.1; always resolve the current live SHA/CI before use.

## What GLOBAL-ACCEL2 Established

The completed engineering phase materially activated the following product paths:

- Watchlist anomaly monitoring;
- StockData Fundamental Health + Cashflow Quality;
- Sector Strength + Concept Context;
- HiThink-qualified A-share unadjusted daily bars as dataset-level runtime primary where configured;
- local Parquet / manifest / DuckDB Research Data Plane foundation;
- RDP-backed Screener with corruption fail-closed behavior;
- Full Market Discovery v0.1 with named, explainable cross-section metrics;
- Campaign-scoped `AI_DRAFT / UNCOMMITTED` with server-owned context witness and existing Formal Decision authority preserved;
- StockData Candidate Research continuation into explicit DRAFT → RESEARCHING → PRE-ENTRY / stop Campaign lifecycle;
- final black-box Holding → Decision → Manual Trade → Attribution/UNPLANNED → Outcome/Review path;
- final black-box Full Market → StockData → Candidate Research path.

The final GLOBAL-ACCEL2 closure audit reported zero validated current CRITICAL/HIGH blockers on the active paths. Verify any claim that matters against live GitHub before relying on it.

## Active Product Truth Track — #162

The next high-value unknown is no longer “can we add another subsystem?” It is:

> Does the current system materially improve the user's real investment decision process enough to justify further engineering investment?

Read Issue **#162** for the exact observation contract.

Core observation target:

- 10 A-share trading days;
- minimum valid sample defined by #162;
- small private working set of real holdings plus one researched candidate;
- normal workflow only; do not manufacture trades, Frozen Decisions or Outcome events to satisfy the sample.

Record privately per meaningful session:

- task;
- elapsed time;
- major page span;
- repeated input;
- confusion;
- value event;
- bypass;
- blocker;
- UNKNOWN / NOT_EVALUATED / ERROR load.

Privacy rule:

- real holdings, quantities, NAV, trade amounts, broker data, private Thesis text and personal notes stay out of this public repository;
- GitHub receives only anonymized aggregate findings;
- detailed Product Reality observations belong in private Notion / local project context.

## Engineering Freeze During Product Reality

Current engineering state is frozen by #203.

Do not autonomously start:

- new feature Slice;
- broad refactor;
- provider expansion;
- data-plane expansion;
- architecture migration;
- historical Draft revival/cleanup;
- broker/order integration;
- automatic trading or automatic Formal Decision behavior.

A new engineering change during the Product Reality phase requires either:

1. a new explicit owner resume/authorization; or
2. a directly observed critical correctness/security/data-loss/path-blocking defect where the latest #203/#162 authority explicitly permits a minimal hotfix.

Do not treat ordinary UX friction as automatic implementation authorization. During PRX1, friction is primarily evidence.

## Known Nonblocking Follow-Up

Issue **#220** remains open for real Market Dump import/update and production-completeness work beyond the accepted Full Market v0.1 local-artifact path.

It is **not** an active engineering keeper while the project is frozen. Do not infer that “open Issue” means “resume now.”

Full Market v0.1 must not be described as universally complete/current by default; provenance and local-artifact limitations remain part of its product contract.

Issue **#169** remains a read-only historical deep-audit asset. Its GLOBAL-ACCEL2 current-live delta found no validated CRITICAL/HIGH blocker on the active paths. Do not restart the full audit during Product Reality unless real-use evidence makes it the highest-value next action.

## Immediate Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve live `feature/research-system-v01` SHA and exact-head CI.
3. Read **#203 latest comment** for current freeze / authorization state.
4. Read **#162 latest comments** for Product Reality state and whether Day 1 has actually begun.
5. Confirm #217 remains closed and inspect any newer owner instruction that may supersede this stage.
6. Inspect live Open / Draft PRs only to avoid duplicate work; historical Drafts are context, not active work.
7. If Product Reality has begun, continue the observation contract rather than inventing engineering work.
8. If Product Reality has not begun, report `READY / NOT_STARTED`; do not fabricate a session.
9. Use named Notion pages below for durable context and private/anonymized Product Reality notes as appropriate.

## Read First — GitHub

1. `AGENTS.md`
2. `docs/CURRENT_STAGE.md`
3. Issue #203 latest comment
4. Issue #162 latest comments
5. live stable / exact-head CI
6. only the source/tests relevant to any observed blocker

Read #217 only when GLOBAL-ACCEL2 historical rationale is needed.

## Read First — Notion

Use the connected Notion workspace when durable/private context is needed. Search these exact page titles first:

1. `Vibe-Research｜A股投资决策系统`
2. `Vibe-Research｜GLOBAL-ACCEL2 全面推进｜2026-08-25`
3. `Vibe-Research｜North Star Autonomous Run 接管｜2026-08-24`
4. `Vibe-Research｜Architecture Reality Map`

Notion does not override live GitHub implementation or execution state. If durable intent and live implementation disagree, report:

`Intent vs Reality conflict`

## Legacy Current-State Documents

The following files are retained as historical context but are **not current recovery authority**:

- `docs/PROJECT_STATE.md`
- `docs/NEXT_TASK.md`
- `docs/CHAT_HANDOFF.md`

Do not use them to override live GitHub, #203, #162 or this recovery coordinate.

## Durable Engineering Invariants

- **User owns formal investment authority.** AI / providers may analyze, explain, challenge or draft, but do not automatically create Formal Decision, Frozen Decision, Trade, attribution or real execution facts.
- **Provider Observation != Canonical Fact Authority.** A provider never becomes a second Holding / Trade / Decision authority.
- **Research Runtime != Canonical Fact Authority.** Bulk/local research paths may optimize discovery without redefining formal fact history.
- **User data and credentials stay local/private.** Real holdings, account data and secrets do not enter Git.
- **Reuse before infrastructure.** Extend existing product/authority paths before creating competing systems.
- **Product Reality evidence outranks speculative feature demand.** During this Stage, observe actual value/friction before expanding architecture.

## Current Acceptance Direction

The current Stage is complete only when Issue #162's formal sample and final report are validly completed, or when the sample is explicitly classified `INVALID_SAMPLE / BLOCKED` with evidence.

At the end of #162, use its evidence-driven conclusion framework rather than sunk-cost reasoning. Do not automatically start the next refactor after the report; first convert observed evidence into one bounded engineering priority and explicitly choose what not to build.

## Deferred / Escalation Boundary

Do not autonomously cross these boundaries:

- destructive migration or irreversible user-data rewrite;
- broker/order/automatic trading execution;
- new paid account/service or material recurring cost;
- credential/account-security changes;
- unresolved conflict between two plausible Formal Authorities;
- irreversible real-user holdings/trades mutation without a safe explicit user action.

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

Then follow #203 + #162. If the project is frozen and Product Reality is merely READY, do not start engineering work without a new explicit owner instruction or an allowed real-use blocker hotfix.
