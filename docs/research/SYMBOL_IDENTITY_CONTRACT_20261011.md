# Global security resolution: bounded identity repair

## Scope and evidence

The local watchlist is deliberately a six-digit A-share code importer. Debate also
requires an A-share code. StockData submits a code rather than offering an
asynchronous suggestion list. It already guards late query responses. No local
name/pinyin picker, autocomplete cache, or stale-candidate Enter path was found.

Simon reference (read statically, never executed):
[SymbolSearch](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/desktop/src/verticals/finance/components/SymbolSearch.tsx)
and [symbolSearch](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/desktop/src/verticals/finance/lib/symbolSearch.ts).
The upstream UI associates candidates with the current query. The applicable
local problem is instead backend selection of the first nonmatching suggestion.
This patch does not claim to deliver the upstream picker or all of matrix item 12.

On base `4fdd41bbeef2a9727e77528f17965da7819ae610`, synthetic provider replies
reproduced these reachable failures through `gstock.us_hk_stock`:

- `AAP` selected `AAPB` from nonmatching suggestions
- Short HK code `700` selected a different partial-code suggestion instead of `00700`
- Distinct exact-code provider identities were resolved by row order
- Explicit Korean input could fall back to another security if no exact Korean
  result existed

These are controlled contract counterexamples, not observed live-provider incidents.
Provider identity fields are the existing `Code`, `MktNum`, and `Name` fields.

## Identity contract

- Match exact code first, then a unique exact name (trimmed, case-insensitive)
- Never infer identity from the first fuzzy/name/pinyin suggestion
- Numeric input of one through five digits expresses HK intent; only documented
  left-zero padding is an alias. Retain the existing padded-query retry on no match
- Bare six-digit codes belong to the A-share page route and do not resolve through
  the global service. Explicit `.KS`, `.KQ`, or `.KR` requires six digits and
  provider market 177. The provider cannot establish a finer Korean exchange
  distinction; this patch does not invent one
- Collapse repeated `(MktNum, Code)` identities. Distinct identities remain
  ambiguous, even when two US provider markets have the same `.O` suffix. No
  unsupported alias relationship is asserted
- Validate supported-market identity fields before selection. Malformed replies
  use the existing backup endpoint; exhausted malformed/transport replies are
  unavailable, not an empty search result. Valid unrelated markets and genuine
  empty lists remain no-match
- No selection means no downstream quote or financial request

## Public response contract

Both `/api/global/stock` and `/api/global/hk/cashflow` retain existing response
shapes and use:

| Case | HTTP | Behavior |
| --- | --- | --- |
| Unique exact supported identity | 200 | Existing data shape |
| No exact identity / unsupported code form | 404 | Existing not-found behavior |
| Distinct exact identities | 400 | Fixed ambiguity message; no candidate silently chosen |
| Exhausted transport or malformed-provider failures | 503 | Fixed unavailable message, distinct from not-found |

The cash-flow endpoint continues returning 404 for a uniquely resolved non-HK
security. The existing API parameter length checks still produce 422.

Public API and AI exception boundaries substitute fixed messages, even if an
exception was constructed with sensitive provider details. Other exception
families and unrelated diagnostics are unchanged. AI tools return their existing
`error` shape; they share the actual resolver. StockData clears the old stock and
renders the API error using its existing request-identity guards. There is no
result cache on this resolver/API/AI call path; provider-host preference is not a
security-result cache. No cache, market provider, formal authority, watchlist
migration, or persistence system is added.

## Validation boundary

- New resolver regressions fail on the unmodified base and pass after the patch
- Synthetic tests cover exact code/name precedence, HK/KR intent, distinct and
  repeated provider identities, malformed/empty replies, backup retry, downstream
  request suppression, and real API/AI consumers
- Frontend API tests verify 400/404/503 are errors, not stock payloads
- Actual StockData is executed in a synthetic hook harness for visible errors and
  late-error isolation; existing watchlist migration and ownership tests remain
  unchanged
- No live providers, models, CLI, browser, full backend suite, deployment, or
  publication were used. Browser acceptance and integration CI remain separate
