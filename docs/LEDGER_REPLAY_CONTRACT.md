# Ledger financial read and replay contract

## Canonical holdings snapshot

`position_reality_service.derive_positions` materializes active account events
(including corrections) and active trades in one read-only SQLite transaction.
An explicit `BEGIN` pins one snapshot before either table is read; a concurrent
writer may make a later result different, but cannot mix older opening/correction
facts with newer trades in a single holdings result. Missing files/tables remain
empty without creating schema. SQLite read failures fail closed.

This guarantee is local to the holdings derivation, not a transaction across all
Account Reality components, separate API requests, or different databases.
Account cash composition still has separate reads; it is not covered by this fix.

## Shared trade ordering

Canonical holdings, its pre-insert proof, and Performance Attribution replay
trades with the same total-order key from `backend/ledger_ordering.py`:

1. execution instant, normalized to UTC;
2. recording (`created_at`) instant, normalized to UTC;
3. immutable `trade_id`, ascending, if both instants tie.

This is a deterministic accounting convention, not proof of exchange execution
priority. The ledger does not store exchange sequence numbers. For otherwise
identical times, creation time precedes the UUID tie breaker; UUID order is never
claimed to be creation order. Missing or timezone-less ordering timestamps fail
closed rather than depending on the machine's local timezone. Performance's
existing missing-execution-time fallback to creation time remains supported.

Legacy opening positions are applied before post-ledger trades, not synthesized
as buys. Active corrections retain their existing account-event ordering and
replace supported economic fields, not trade identity/timestamps. Voided and
not-executed rows remain excluded. Fee/cost formulas and ledger boundary checks
are unchanged. Performance still reports corrected trades as unavailable pending
reconciliation and does not invent legacy opening costs; parity is therefore
asserted only for equally covered, uncorrected trade facts.

## Historical records and provenance

This changes read-time derivation only. No trade, saved performance snapshot,
Frozen Decision or Formal Outcome is migrated or overwritten. Recomputing an old
ledger can legitimately produce a different result where prior consumers used
incompatible tie/offset ordering; an already saved formal record remains its
original evidence. Performance fingerprints already bind the ordered selected
trade IDs, so a changed replay sequence changes the new computation fingerprint.
The weighted-average formula and existing authority payload contract are unchanged.

## Regression coverage

`TestFinancialReadConsistency` in `test_position_reality_service.py` covers a real
SQLite WAL interleaving (opening correction plus sell between table reads),
equal execution-time cost/fee parity, same-time buy/sell from zero holdings,
UTC-normalized execution and creation times, no read-time mutation, and missing
schema behavior. Existing position, performance, ledger, account and formal
outcome suites cover corrections, unknown opening costs, voiding and immutable
formal boundaries. These are synthetic offline checks, not live financial acceptance.
