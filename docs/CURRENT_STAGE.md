# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-25

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

Do **not** update it for every commit, CI run, test result, temporary worktree or minor implementation detail. At a Stage transition or final handover, refresh the recovery coordinates once. If this file becomes stale, live GitHub wins and the recovering Agent should report the conflict rather than asking the user to reconstruct history.

Do not store an “exact current stable SHA” here: merging this file would immediately make that SHA stale by construction. Recovering Agents must resolve `EXACT_STABLE_SHA` from live GitHub.

## Product North Star

> Vibe-Research is a single-user, local-first A-share investment research and decision system. Its purpose is to reduce real buy / hold / sell decision errors around the user's holdings and candidates; final Formal Decision and real trading authority remain with the user.

## Current Stage

**GLOBAL-ACCEL2 — Full Project Advancement**

Owner direction:

> 全面推进，不要聚焦 1～2 个小问题，着眼全局。

Current state / authorization authority:

- GitHub Issue **#203** — read the **latest comment**, not the original issue body.
- Current expected authorization coordinate: `PROJECT_FREEZE = PARTIALLY_LIFTED_FOR_GLOBAL_ADVANCEMENT_RUN`.
- Coordination Epic: **#217 — GLOBAL-ACCEL2 — Full Project Advancement: Product Truth, Decision Flow, Research & Discovery**.

Stable recovery coordinate:

- Stable branch: `feature/research-system-v01`
- Exact stable SHA: **resolve live; intentionally not persisted here**
- Last completed product run before GLOBAL-ACCEL2: #210 Watchlist Anomaly, #212 Fundamental Health + Cashflow Quality, #216 Sector Strength + Concept Context.

## Active Global Workstreams

Treat #217 as the top-level scope. Recover live state before selecting an implementation lane.

### A — Product Truth / Real-Use Readiness

- Issue **#162 Product Reality Sprint** remains the formal real-use truth gate.
- Historical prerequisites #164 security baseline and #171 Holding single-writer closure are merged.
- During GLOBAL-ACCEL2, use short workflow/product-reality smokes to expose structural blockers.
- Do not start #162's formal 10-trading-day feature-freeze observation window until GLOBAL-ACCEL2 reaches a stable engineering baseline.

### B — Core Decision Workflow

- Existing high-value candidate: **#206 Campaign AI Draft → Formal Decision**.
- Verify live anti-rewheel first; if the gap still exists, advance the real Holding/Candidate → Research → Thesis/Evidence → Draft → Preview → explicit Freeze → Trade → Outcome path.
- Reduce repeated input and context loss without creating a second Decision/Thesis/Holding authority.

### C — Candidate Research / P1

Build a coherent candidate-decision path from existing StockData, Fundamental Health, Sector/Concept context, valuation/risk, Evidence and Campaign capabilities before inventing new frameworks.

### D — P2 Discovery / Research Data Plane

Re-evaluate the already-qualified HiThink Market Dumps / Parquet / DuckDB path as bulk Research Data Plane input and connect it toward existing Screener / Sector / Candidate research.

Keep `Research Runtime != Canonical Fact Authority`.

### E — Correctness Audit

- **#169** runs as a parallel **READ_ONLY** cross-cutting audit.
- Its old lane references are historical; final findings must be delta-revalidated against the then-live GLOBAL-ACCEL2 stable.
- Only validated CRITICAL/HIGH findings directly affecting active user paths should interrupt product work.

### F — Product Surface Coherence

Evaluate the whole user flow, not isolated pages:

`Today / Decision Inbox → Watchlist / Stock / Sector Research → Campaign / Thesis / Evidence → Formal Decision → Trade / Attribution → Outcome / Review → Screener / Discovery`

Fix navigation/context/repeated-input problems only where they materially break this flow.

## Immediate Recovery Actions

1. Read `AGENTS.md`.
2. Resolve live stable SHA and exact-head CI.
3. Read #203 latest comment for authorization state.
4. Read #217 and its latest comments for global execution state.
5. Inspect live Open / Draft PRs. Historical Drafts are context only unless #217 explicitly reuses them.
6. Identify the active keeper implementation lane, if any; do not create a duplicate path.
7. Read #206 / #162 / #169 only as required by the current workstream.
8. Read `docs/PRODUCT_NORTH_STAR_V01.md` and `docs/ARCHITECTURE.md` only when the active work requires their durable contracts.
9. Use named Notion pages only for durable Product / Architecture context.

## Read First — Notion

Use the connected Notion workspace when durable context is needed. Search these exact page titles first:

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

Do not use them to override live GitHub, #203, #217 or this recovery coordinate.

## Durable Engineering Invariants

- **User owns formal investment authority.** AI / providers may analyze, explain, challenge or draft, but do not automatically create Formal Decision, Frozen Decision, Trade, attribution or real execution facts.
- **Provider Observation != Canonical Fact Authority.** A provider never becomes a second Holding / Trade / Decision authority.
- **Research Runtime != Canonical Fact Authority.** Bulk/local research paths may optimize discovery without redefining formal fact history.
- **User data and credentials stay local.** Real holdings, account data and secrets do not enter Git.
- **Reuse before infrastructure.** Extend existing Watchlist, StockData, Sector, Campaign, Fact Lake, provider and research capabilities before creating competing systems.
- **Global advancement != uncontrolled parallel coding.** One implementation lane per overlapping authority/product surface; independent read-only research/audit may run in parallel.

## Current Acceptance Direction

GLOBAL-ACCEL2 is complete only when the project has materially advanced across the whole product, not when one PR merges.

Strong completion evidence should include, where live evidence supports it:

- no known structural blocker in the holding → research → decision → trade → outcome workflow;
- #206 resolved or superseded by an equivalent real product path;
- Candidate Research has a coherent usable path;
- P2 Discovery / Research Data Plane has a real bulk-data/query foundation connected toward product use, or a concrete evidence-backed blocker;
- #169 has a current delta verdict and validated CRITICAL/HIGH findings are resolved or explicitly blocked;
- no half-finished keeper PR;
- stable exact-head CI green;
- recovery coordinates and Notion durable context synchronized;
- #162 ready to start its formal 10-trading-day Product Reality Sprint on a stable baseline.

Then restore project freeze.

## Deferred / Escalation Boundary

Do not autonomously cross these boundaries:

- destructive migration or irreversible user-data rewrite;
- broker/order/automatic trading execution;
- new paid account/service or material recurring cost;
- credential/account-security changes;
- unresolved conflict between two plausible Formal Authorities;
- irreversible real-user holdings/trades mutation without a safe explicit user action.

Normal architecture, implementation, provider, UI, testing, Ready and Merge decisions inside #217 remain autonomous when their independent Gate and current-base CI pass.

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

Then continue the highest-priority unblocked work allowed by #217 and the latest #203 authorization state.
