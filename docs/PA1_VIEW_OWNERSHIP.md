# PA1 asynchronous view ownership

The attribution page's live calculations and historical snapshot reads share one
latest-view request generation. The selected result, historical label, error and
loading completion may only be updated by that generation while the page remains
mounted. Date edits invalidate the previous read immediately, before the next
automatic calculation effect. This does not alter the calculation or date-filter
contract. Failed or unreadable results are unavailable, not evidence of zero trades.

The historical snapshot list has its own request generation. Its refresh failure
is displayed separately; it cannot convert a confirmed snapshot write into a
failure or erase a newer list. Reading a snapshot never mutates its saved payload.

## Snapshot writes

Freezing remains an explicit POST with the dates captured at the click. A
synchronous in-flight guard prevents a rapid duplicate submission. The write is
neither cancelled when the view changes nor automatically retried. Once confirmed:

- the server's actual snapshot ID and calculation date are acknowledged
- if the same view is still selected, the confirmed result may replace it and
  invalidates older reads; otherwise the newer selected view is preserved
- the history list refresh is independent of the acknowledgement
- after in-app navigation unmounts the page, the existing application toast shows
  completion; no stale page-state update is attempted

If the write response is not confirmed, the UI asks the user to inspect history
before deciding whether to retry. It does not assert that the server definitely
failed to write. Closing the entire tab or application is outside the in-app toast
lifetime; this slice adds no durable operation log or idempotency protocol.

Read requests may finish in transport after their view is invalidated; they cannot
change the new view. Existing stored snapshots, backend APIs, financial arithmetic,
PIT and quote-time semantics are unchanged.

## Regression scope

Deferred synthetic responses reproduce the original mixed-state defect: live A
arriving after historical B previously replaced the values under B's label; late
snapshot A also replaced the more recently selected B. Tests cover both directions,
date changes, obsolete error/finally handlers, unmount cleanup, missing payloads,
freeze success/uncertainty after view changes, list refresh failure, double clicks
and read-only list races. Real browser fixtures at 390/1440px use intercepted
synthetic APIs only, including explicitly counted simulated snapshot POSTs; they
do not create user business records or call a market/model provider.
