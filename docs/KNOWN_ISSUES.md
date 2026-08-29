# Known Limitations — Current Product Boundary

This file records durable limitations only. Exact defects, active blockers and CI failures belong in
live GitHub Issues/PRs rather than a copied status table.

The former early-P0 limitation snapshot is preserved in Git history immediately before this change. It
was retired because several entries predated canonical Position Reality, Formal Decision/Outcome and
Native Intel, and therefore described current capabilities incorrectly.

## Product value is not yet proven

The formal backend chain and user surfaces exist, but engineering completion does not prove that the
system improves the Owner's real investment process. Issue
[#162](https://github.com/guilaile95/Vibe-Research/issues/162) owns the 10-trading-day Product Reality
observation. Until that evidence exists, navigation consolidation, workflow simplification and future
feature priorities remain hypotheses.

## Data is best-effort, not a market-data SLA

Public market/news providers can be unavailable, delayed, incomplete, rate-limited or semantically
incompatible. The product must keep freshness, coverage, provenance and `partial / stale / unavailable`
visible. Missing data must not become zero, neutral, healthy or invented certainty.

The system is not a reliable real-time terminal and does not provide 24/7 protection. Its default mode
runs when the local application is open.

## Account and execution facts remain manual

Vibe does not connect to a broker and does not place, cancel or infer orders. Holdings, cash events and
executed trades depend on explicit user input and canonical local ledgers. A missing attribution stays
`UNALLOCATED / RECONCILIATION REQUIRED` unless the user explicitly binds a Frozen Decision or marks
an `UNPLANNED` origin.

Estimated amounts are not guaranteed fills and do not silently invent fees, slippage, tax, sellable
quantity or broker state.

## Native Intel relevance is intentionally simple

Native Intel provides deterministic public-information observations and source health. Security
association currently relies on explainable code/company/industry/concept terms, so it can miss useful
items or include broad/noisy matches. It is a research-priority input, not Canonical Fact or BUY/SELL
authority. Useful-item and obvious-noise counts should be measured during Product Reality before adding
AI/vector relevance infrastructure.

## Legacy product surfaces still exist

Some legacy advice, cockpit, feedback, evidence and attribution views remain reachable beside the
formal Campaign/Thesis/Decision/Outcome chain. They are not permission to create a second authority.
Which surfaces should be hidden or merged must be decided from real page-span, confusion and bypass
evidence rather than another speculative redesign.

## Privacy boundary

Real holdings, cash, trade amounts, private Thesis text, broker data, credentials and model keys remain
local/private and must not be committed to this public repository or posted in public Issues/PRs.

For the current engineering state, read [`CURRENT_STAGE.md`](CURRENT_STAGE.md), live GitHub and root
[`AGENTS.md`](../AGENTS.md). Do not infer current blockers from this limitations document.
