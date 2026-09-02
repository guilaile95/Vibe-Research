# Current Stage — Recovery Coordinates

Last reviewed: 2026-09-03

This file is a recovery pointer, not Engineering Truth and not a second task database.
Always resolve live GitHub state before acting; do not persist an exact stable SHA here.

## Current Product Stage

**P1-PRX1 — Product Reality: 10-trading-day real-use observation**

The durable product-value contract is Issue
[#162](https://github.com/guilaile95/Vibe-Research/issues/162).

Last synchronized state:

```text
STATE = READY_FOR_FORMAL_10_TRADING_DAY_OBSERVATION
FORMAL_OBSERVATION_DAY_1 = NOT_STARTED
OBSERVATION_SAMPLE_INVALIDATED = NO
BLOCKED_BY = NONE
```

This is not an engineering feature lane. Day 1 begins only when the Owner uses the accepted stable
build for a real A-share decision workflow. CI, browser smoke, setup checks, demos, and synthetic data
must never be counted as Product Reality evidence.

## Current Engineering Default

Issue [#203](https://github.com/guilaile95/Vibe-Research/issues/203) is the live freeze authority.
The default engineering state is **FROZEN** unless its latest comment records a narrow active Owner
override.

A clear next action does not itself authorize implementation. Historical Draft PRs and old agent lane
assignments remain archival context and must not be revived automatically.

## Stable Product Foundation

The accepted stable line already contains the product foundation required for the observation:

- canonical Position / Account Reality and single-writer Holding read path;
- Campaign, Current/Formal Thesis and Evidence;
- Hard Risk, Material Change and Critical Data boundaries;
- explicit Decision Proposal, optional Challenge and immutable Frozen Decision;
- manual Trade Ledger, explicit attribution or explicit UNPLANNED origin;
- Formal Outcome / review worklist;
- local data snapshot/restore and local API boundary;
- local Native Intel for Intel, StockData and Watchlist without TrendRadar sidecar or MCP runtime
  dependency.
- Candidate Research for an explicitly chosen security, including PRE-ENTRY research, formal
  evidence/thesis, bounded decision preview and immutable decision commit.
- bounded, deterministic full-market Discovery on `/screener`, with separate SHORT/SWING/MEDIUM
  research queues and an explicit handoff to Candidate Research; Discovery creates no formal state
  and emits no BUY action.
- Wave 1 (UPSYNC2, PRs #262/#263/#264) already merged into stable:
  - isolated Codex subscription page-aware chat runtime (`agent-runtime/` + `backend/agent_runtime.py`,
    :8911; NON_AUTHORITATIVE_AI_DRAFT, no shell / web / local disk / Vibe MCP / plugins /
    multi-agent / Formal authority write);
  - MyReports full-text knowledge and retrieval with source/page citations;
  - Research Continuity change digest and decision calendar read model.

These capabilities being present and tested does not prove product value. The next truth gate is real
usage, not another feature-completeness pass.

## Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve the live `feature/research-system-v01` HEAD and exact-head CI.
3. Read the latest comments on #203 and #162.
4. Inspect all Open PRs before creating work; treat old Drafts as historical unless the current live
   authority explicitly names one.
5. Inspect the local workspace before touching files; preserve uncommitted work.
6. If engineering is frozen and no active override exists, do not code. Help the Owner start or record
   a real Product Reality session instead.
7. If Day 1 has started, use #162's evidence fields and keep private holdings, amounts, Thesis text and
   broker data out of public GitHub.

## Product Reality Operating Boundary

Use the smallest natural path only:

```text
Today / Decision Inbox
→ the real Campaign that needs attention
→ Thesis / evidence update only when something materially changed
→ explicit Formal Decision only when a real decision exists
→ Trade attribution only when a real trade occurred
→ Outcome / Review when its real boundary is reached
```

Record friction rather than immediately coding around it: elapsed time, page span, repeated input,
confusion, bypasses, blockers, UNKNOWN load, and meaningful value events. Also record Native Intel
useful-item versus obvious-noise counts when it is used in a real decision.

## Deferred Until Real-Use Evidence

Do not start these merely because they remain conceivable:

- broad navigation or Home redesign;
- new formal states, ledgers or authority layers;
- Native Intel vector/AI relevance infrastructure;
- notification or background-agent expansion;
- Discovery follow-ons beyond the bounded #244 v0.1 vertical;
- behavioral scoring, calibration, risk-budget expansion or model governance;
- historical Draft PR cleanup as part of a product feature.

## Durable Invariants

- The user owns formal investment and trade authority.
- Public-provider observations are not Canonical Fact authority.
- Real holdings, account values, credentials and private research stay local/private.
- UNKNOWN, NOT_EVALUATED, ERROR and empty remain distinct.
- Reuse accepted capabilities before adding dependencies.
- Product Reality Day 1 cannot be backfilled or fabricated.
