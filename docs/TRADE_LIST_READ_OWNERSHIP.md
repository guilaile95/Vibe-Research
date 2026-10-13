# Trade-list read ownership

The Trades page distinguishes editable draft filters from applied filters.
Typing alone does not issue a list request. Submitting valid filters, resetting
filters or changing pages invalidates the previous list read immediately; invalid
filter drafts do not replace the accepted scope.

Only the current request for the current applied-filter object and offset may
update list rows, read errors or loading completion while the page is mounted.
Old responses, errors and finalizers are ignored. Reads may still finish in
transport after invalidation; no claim of server-side cancellation is made.

The list refresh callback is stable and consults the current applied scope. Thus
an existing transaction handler completing later can refresh the user's latest
list rather than querying the filters captured when that handler began. Calling
that read callback after unmount is a no-op.

The five create/void/attribution/unplanned/activation handler blocks remain
byte-identical to the preceding verified baseline. This slice changes no write
endpoint, body, completion handling, transaction policy, arithmetic, data schema,
detail-selection logic or provider. It performs no automatic business write.

## Regressions

The prior real list handler was reproduced offline with two deferred responses:
000002 returned first, then old 000001 replaced it while the applied filter was
still 000002. Focused tests cover success/error/finally ordering, retries, draft
versus applied input, filter reset, pagination, unmount and retained refresh
callbacks using the new scope. Existing trade query/draft helper tests are retained.

Synthetic real-browser fixtures at 390/1440 use the actual `/trades` route and
rendered trade IDs, query parameters and current filter controls. They include
old errors, a stale finalizer while the newer request is held, reset during a
pending filter/page request, current failure/retry and in-app unmount. All API
traffic is intercepted and all non-GET requests must remain absent. No user ledger
is used. This is bounded regression evidence, not closure of the unavailable
original full-QA findings matrix.
