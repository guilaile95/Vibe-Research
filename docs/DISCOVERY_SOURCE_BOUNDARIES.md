# Discovery and source boundaries

Discovery is a bounded research queue, not an all-market investment ranking.
The price conditions are unchanged except that finite negative and zero 20/60-day
returns are now known failed conditions rather than missing values. Missing or
unusable historical returns may still enter through the existing sector fallback;
that path is explicitly labelled a degraded clue, not a complete match.

## What the queue covers

- Provider-returned Shanghai/Shenzhen main-board, ChiNext and STAR securities;
  this path excludes Beijing and does not establish complete A-share coverage.
- Up to 24 deduplicated, turnover-ranked initial candidates receive additional
  financial/announcement checks across the three strategy lanes.
- Each lane returns at most 12 items, ordered by research priority and then code.
  A code-order tie is not a relative investment-value score.
- Industry and theme filters operate on the returned queue, not a new scan of an
  entire industry. A filtered empty queue does not prove no relevant company exists.
- Qualification omissions, queue truncation and omitted exclusion records are
  exposed independently. Exclusion counts are records, not unique securities.

## Requests are not complete material

Announcement adapters can return an explicit coverage envelope without changing
the legacy list response for other callers. The current reader requests one page
of at most 15 metadata rows. Even a successful short or empty page does not prove
that the requested date window is complete; title/link rows are not announcement
full text. Request status and material completeness are separate fields in the
Discovery/calendar projections. Financial freshness remains conservatively
qualified; the changes do not manufacture a HIGH rating.

## AI paths are different

Ordinary API chat may call existing allowlisted public-data tools and is not
limited to selected excerpts. Explicit selected-page chat uses server-validated
page content and disables data tools. Codex Subscription uses its restricted
page-context runtime. None of these paths independently establishes source truth.

An independent saved AI note preserves the answer and optional source links, not
all selected excerpt versions or returned tool bodies. Legacy answers do not gain
missing provenance retrospectively. The displayed limitation is deliberately not
a new claim of reproducible historical analysis.

## Verification scope

Focused unit fixtures cover finite positive/negative/zero returns, missing and
nonfinite values, stale history, fallback labelling, bounded queues, malformed
announcement payloads, provider totals, short/empty first pages and source labels.
The existing production browser acceptance adds visible queue-scope and AI-mode
checks with synthetic local history and no live model call. Exact execution status
belongs to the task's CI run, not to this contract document.

These tests are not real-provider coverage, live-model quality, profitability,
natural user value, deployment, or Product Reality Day 1 evidence.
