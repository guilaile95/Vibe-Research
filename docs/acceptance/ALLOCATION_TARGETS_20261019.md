# User-defined allocation comparison

## Scope

The Portfolio page adds an explicit, initially empty target editor. This bounded first version supports CN/CNY security codes and `CASH`, with a user-entered effective date and either partial targets (sum ≤100%) or full targets (sum exactly 100%). Weights have at most two decimal places. Unspecified target weights remain unknown; they never become cash or zero targets. There is no default policy, portfolio recommendation, order, quantity, rebalance automation, provider fetch, or model call.

Versions are append-only in the existing private facts database, selected by greatest effective date not later than the current UTC day, then greatest version for that date. A future version does not activate early; a later-created backdated version does not displace a newer effective policy. Saves use optimistic latest-version checks. GET does not initialize a database. No second browser-storage authority is created.

## Actual-value contract

Actual holdings come from `read_current_holdings_snapshot`; position authority must be canonical. Quotes reuse the existing immutable `cn_quote_ref` archive reader, never the live portfolio quote reader. Only acquired, non-fixture receipts with a matching symbol/currency and both fresh archive and source timestamps are usable. This first version reads today's cutoff receipts only, at most eleven held securities; absent archives, old cutoffs, and larger books explicitly remain unavailable. No sample quotation can become an actual account price.

The denominator is the existing confirmed account-total-assets fact. Cash and assets require the same confirmation ID. All active holdings must have usable prices, nonnegative quantities and supported currency. Tracked stock value plus cash must reconcile to that denominator within the larger of CNY 0.01 and 0.0001%. Otherwise all actual weights and deviations remain unknown: no partial-book renormalization or invented residual cash. Explicit zero holdings and zero cash are valid. A target for an absent holding becomes zero actual weight only after the entire canonical book is proven complete. Current position and account facts are read again to detect changes during composition.

Actual weight is value / confirmed account assets. Drift is actual minus user target in percentage points. Unknown industry membership is disclosed for every security; sector authoring is deferred because cached receipts do not prove sector membership. No FX conversion is implemented. Mixed-time visibility is not settled NAV or a complete-account accounting claim.

The UI hides old actual weights during refresh/save and after the earliest source quote expires. It preserves edit values on failure and rejects optimistic conflicts rather than overwriting another version. The user refreshes and reopens the editor to base a new edit on the current version.

## Verification and limits

Offline synthetic tests cover sums and decimal rounding, partial/full targets, cash, unknown industries, absent/zero/negative holdings, FX rejection, quote gaps, zero denominators, unmatched account confirmation, asset reconciliation, effective versions, optimistic conflicts, corrupted history, read-only GET, receipt fixture/staleness rejection, and mutations during composition. Frontend tests cover explicit input parsing and stale/version guards. Browser runtime acceptance was not performed; the previously denied browser route was not retried.

Implementation is original project code. Wealthfolio was design inspiration only; no source, assets, or licensed implementation were copied. This deliverable does not assess upstream licensing beyond that boundary.
