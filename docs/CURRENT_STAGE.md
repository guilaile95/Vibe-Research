# Current Stage — Recovery Coordinates

Last reviewed: 2026-09-10

This file is a recovery pointer, not Engineering Truth and not a second task database.
Always resolve live GitHub state before acting; do not persist an exact stable SHA here.

## Current Product Stage

**Planning Parity continuation; Product Reality remains ready but is not active.**

The durable Product Reality contract remains Issue
[#162](https://github.com/guilaile95/Vibe-Research/issues/162).

Last synchronized state:

```text
PRODUCT_REALITY_STATE = READY_NOT_ACTIVE
FORMAL_OBSERVATION_DAY_1 = NOT_STARTED
OBSERVATION_SAMPLE_INVALIDATED = NO
CURRENT_SEQUENCE = PLANNING_PARITY_CONTINUES
```

Owner sequencing decision: Product Reality is not a prerequisite for continuing Planning Parity.
Engineering may continue through narrowly scoped, explicitly bounded Planning Parity slices while Day 1
has not started. Once the Owner actually starts the formal Product Reality observation, the observation
freeze in #162 applies for the duration of that active sprint.

Day 1 still begins only when the Owner uses the accepted stable build for a real A-share decision
workflow. CI, browser smoke, setup checks, demos, and synthetic data must never be counted as Product
Reality evidence.

## Current Engineering Default

Issue [#203](https://github.com/guilaile95/Vibe-Research/issues/203) remains the live engineering authority.
The default state is **FROZEN between slices**, unless its latest comment records an active Owner/PM
Planning Parity authorization or another narrow Owner override.

A clear next action does not itself authorize unrelated implementation. Historical Draft PRs and old
agent lane assignments remain archival context and must not be revived automatically.

## Stable Product Foundation

The accepted stable line already contains substantial product foundation:

- canonical Position / Account Reality and single-writer Holding read path;
- Campaign, Current/Formal Thesis and Evidence;
- Hard Risk, Material Change and Critical Data boundaries;
- explicit Decision Proposal, optional Challenge and immutable Frozen Decision;
- manual Trade Ledger, explicit attribution or explicit UNPLANNED origin;
- Formal Outcome / review worklist;
- local data snapshot/restore and local API boundary;
- local Native Intel for Intel, StockData and Watchlist without TrendRadar sidecar or MCP runtime
  dependency;
- Candidate Research for an explicitly chosen security, including PRE-ENTRY research, formal
  evidence/thesis, bounded decision preview and immutable decision commit;
- bounded, deterministic full-market Discovery on `/screener`, with separate SHORT/SWING/MEDIUM
  research queues and an explicit handoff to Candidate Research; Discovery creates no formal state
  and emits no BUY action;
- Research Event Calendar, current Portfolio Risk Context, Dragon-Tiger market discovery and
  deterministic Pattern Discovery;
- Wave 1 (UPSYNC2, PRs #262/#263/#264):
  - isolated Codex subscription page-aware chat runtime (`agent-runtime/` + `backend/agent_runtime.py`,
    :8911; NON_AUTHORITATIVE_AI_DRAFT, no shell / web / local disk / Vibe MCP / plugins /
    multi-agent / Formal authority write);
  - MyReports full-text knowledge and retrieval with source/page citations;
  - Research Continuity change digest and decision calendar read model.

These capabilities being present and tested still do not prove product value. Product Reality remains a
separate truth gate, but Owner has explicitly chosen to continue Planning Parity before activating it.

## Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve the live `feature/research-system-v01` HEAD and exact-head CI.
3. Read the latest comments on #203 and #162.
4. Inspect all Open PRs before creating work; treat old Drafts as historical unless the current live
   authority explicitly names one.
5. Inspect the local workspace before touching files; preserve uncommitted work.
6. If a current Planning Parity authorization exists in #203, execute only that bounded slice and
   restore the freeze after verified closure. If no active authorization exists, remain frozen until the
   Owner or PM operating under the Owner's continuing Planning Parity direction authorizes the next
   bounded slice.
7. If Product Reality Day 1 has started, use #162's evidence fields, activate its observation freeze,
   and keep private holdings, amounts, Thesis text and broker data out of public GitHub.

## Product Reality Operating Boundary

When the Owner starts Product Reality, use the smallest natural path only:

```text
Today / Decision Inbox
→ the real Campaign that needs attention
→ Thesis / evidence update only when something materially changed
→ explicit Formal Decision only when a real decision exists
→ Trade attribution only when a real trade occurred
→ Outcome / Review when its real boundary is reached
```

During an active Product Reality sprint, record friction rather than immediately coding around it:
elapsed time, page span, repeated input, confusion, bypasses, blockers, UNKNOWN load, and meaningful
value events. Also record Native Intel useful-item versus obvious-noise counts when it is used in a real
decision.

## Planning Parity Continuation Boundary

Before Product Reality is activated, Planning Parity may continue when each slice:

- closes a concrete gap against the external planning specification or a confirmed product requirement;
- reuses current stable capabilities before adding new providers or authorities;
- has a bounded contract and explicit non-scope;
- preserves no-broker / no-auto-trading / private-data boundaries;
- uses minimum sufficient validation and an independent Gate;
- restores the project freeze after verified closure.

Do not create work merely for elegance, broad modernization, generic infrastructure, or feature-count
completeness. Product Reality can still later invalidate, simplify, or reprioritize implemented features.

## Durable Invariants

- The user owns formal investment and trade authority.
- Public-provider observations are not Canonical Fact authority.
- Real holdings, account values, credentials and private research stay local/private.
- UNKNOWN, NOT_EVALUATED, ERROR and empty remain distinct.
- Reuse accepted capabilities before adding dependencies.
- Product Reality Day 1 cannot be backfilled or fabricated.
- Product Reality is a separate validation gate, not a prerequisite for Owner-authorized Planning Parity work.
