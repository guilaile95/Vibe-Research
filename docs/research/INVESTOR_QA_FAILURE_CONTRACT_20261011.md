# Investor Q&A failure contract — 2026-10-11

## Bounded change

The existing CNInfo reader now propagates a fixed safe failure for HTTP, transport,
JSON, malformed response/row, and unresolved-company failures. Only a well-shaped
`rows: []` response after a resolved company lookup is a successful empty page.
Optional company, answer and answerer fields remain nullable/missing; unanswered
questions remain records. Existing Beijing-time conversion and missing-time behavior
are retained. No new provider, market router or endpoint was added.

The existing API turns failures into HTTP 502; the existing cache does not store
raised failures and permits the next independent request to recover. The existing
AI tool `query_investor_qa` emits an error with safe wording. StockData already
maps HTTP failure to source-unavailable rather than successful empty evidence.
A source lookup with no company match does not prove absence of Q&A.

## Source-to-consumer evidence

- `backend/astock.py:investor_qa`: CNInfo lookup and question page
- `backend/app.py:investor_qa`, `_cached`, `TTLCache`: 900-second success cache
- `backend/ai_tools.py:_investor_qa`, `exec_tool`: existing 12-row excerpt projection
- `frontend/src/lib/api.ts:investorQa`, `pages/StockData.tsx`,
  `lib/stockDataEvidence.ts`: independent loading/error/empty states

Before repair, synthetic timeout, invalid JSON, and missing response fields were
indistinguishable from a successful empty page and stayed cached after simulated
provider recovery. The existing cache itself already correctly excludes exceptions.
The repair belongs at the reader boundary, not in a duplicate cache implementation.

## Upstream assessment and deferred capability

Static source inspected at Simon commit
[d643728e79b955dfdcdcd8b0dd362bd7c90c35c8](https://github.com/simonlin1212/Vibe-Research/tree/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8):
[astock_ported.py](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/astock_ported.py),
`sse_e_interaction` and its UID/HTTP helpers, plus its registry and mapper.
Fetched upstream code was not executed or imported.

That implementation provides Shanghai `60/68/900` company Q&A through
`sns.sseinfo.com`. It resolves company UID by exponential/binary pagination of
`/allcompany.do`, then POSTs to `/ajax/userfeeds.do`. It supplies no bounded single
code-to-UID lookup in the inspected implementation. Cold lookup is described by
upstream as about 10–13 requests; its loops have no total request cap/deadline,
per-call timeout defaults to (10, 40) seconds, and this path has no rate limiter.
Thus it is not adopted into the interactive workflow.

`answered` (registry default) excludes unanswered questions; `questions` includes
them with nullable answer. Upstream claims roughly a month of company history,
not complete history. Empty SSE results require an explicit empty-page marker;
unknown markup and mismatched company codes raise errors. Its dataframe retains
source, source URL and fetch time. These are useful future contract requirements,
not a validated live service contract for this application.

Coverage status:

- CNInfo: existing route retained, failure vs resolved empty improved
- Shanghai/SSE: pending capability; current source routing does not establish coverage
- Beijing and non-company securities: no coverage claim; no-match now fails safely
- Market aliases: HTTP still accepts six digits only; reader/AI alias normalization
  is not added. Upstream prefix/suffix normalization is not copied wholesale

The upstream claim that CNInfo returns no Shanghai results is an upstream report,
not live evidence obtained in this task. No new market-specific 501 is inferred.

## Verification boundary

Focused guarded synthetic tests cover reader/API/AI safe errors, no failed cache
entry, recovery, successful empty caching, malformed fields, unanswered questions,
Beijing-time behavior, adapter truncation and existing source-safe API behavior.
No live provider, credential, model, browser, full-backend suite, merge, publication
or deployment was performed. Source text remains untrusted data. This change does
not add new source provenance, demonstrate Shanghai availability, or establish
complete question history.
