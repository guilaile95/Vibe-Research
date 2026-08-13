# P0-TB2 Formal Trade Attribution Persistence Ledger v0.1

## Product question

> How is a FormalTradeAttribution already constructed and validated by
> P0-TB1 stored durably, append-only, and fail-closed?

## Anti-rewheel

```text
EXISTING_FORMAL_TRADE_ATTRIBUTION_STORE = NO
P0_TB1_REUSED = YES
```

P0-TB1 is the domain contract. Trade Ledger / Campaign Store / Frozen
Decision Store are other ledgers. This slice does not alter their schemas.

## Role

```text
TB2_ROLE = FORMAL_TRADE_ATTRIBUTION_PERSISTENCE_AUTHORITY
STORE_SCHEMA_VERSION = formal-trade-attribution-ledger.v0.1
DOMAIN_SCHEMA_VERSION = formal_trade_attribution.v0.1
```

TB2 persists. It does not generate identity, infer campaigns, or verify
current trade / decision / campaign liveness.

## Invariants

```text
APPEND_ONLY = YES
ONE_TRADE_ONE_ATTRIBUTION = YES
ONE_DECISION_MANY_TRADES = YES
EXACT_REPLAY_IDEMPOTENT = YES
CONFLICTING_REPLAY_FAIL_CLOSED = YES
READ_MISSING_DB_CREATES_FILES = NO
IMPORT_SIDE_EFFECT = NO
AUTO_MIGRATION = NO
TRADE_LEDGER_SCHEMA_CHANGED = NO
ATTRIBUTION_ID_GENERATED_BY_TB2 = NO
CAMPAIGN_INFERENCE = NO
CURRENT_TRADE_BINDING_VERIFIED = NO
CURRENT_DECISION_VALIDITY_VERIFIED = NO
CURRENT_CAMPAIGN_STATUS_VERIFIED = NO
TRADE_VOID_DELETES_ATTRIBUTION = NO
TRADE_CORRECTION_REWRITES_ATTRIBUTION = NO
```

Write and read both call ``formal_trade_attribution.from_dict``. Tampered
rows fail closed.

## Path

1. explicit ``db_path``
2. ``VIBE_RESEARCH_TRADE_ATTRIBUTION_DB``
3. ``VR_DATA_DIR`` / ``formal_trade_attributions.sqlite3``
4. ``~/.vibe-research/formal_trade_attributions.sqlite3``

Resolution is pure. Reads use SQLite ``mode=ro``. First write uses
``O_EXCL`` ownership to initialize schema.

```text
O_EXCL_OWNER = ONLY PROCESS ALLOWED TO INITIALIZE
NON_OWNER_EMPTY_DATABASE = WAIT_BOUNDED
NON_OWNER_EMPTY_DATABASE_AFTER_TIMEOUT = FAIL_CLOSED
```

A non-owner that sees an empty file waits; it does not treat
``existed_at_start`` as immediate corruption. After the wait budget the
empty leftover file still fails closed as ``INITIALIZATION_INCOMPLETE``.
Owner crash does not auto-rebuild or delete the file.

Read path: a true missing regular file returns empty; a directory,
permission/stat error, or other non-file path fails closed and is never
classified as missing.

```text
MISSING_DB_EMPTY_ALLOWED = YES
NON_FILE_PATH_EMPTY_ALLOWED = NO
STAT_ERROR_EMPTY_ALLOWED = NO
UNREADABLE_DB_EMPTY_ALLOWED = NO
```

``UNIQUE(trade_id)`` must be a full table uniqueness constraint
(``unique=1``, ``partial=0``). A partial unique index on ``trade_id``
is not accepted.

```text
GLOBAL_UNIQUE_TRADE_ID = YES
PARTIAL_UNIQUE_ACCEPTED = NO
PARTIAL_UNIQUE_TRADE_ID_SCHEMA = REJECTED
```

## Files

```text
backend/formal_trade_attribution_store.py
backend/tests/test_formal_trade_attribution_store.py
docs/p0/FORMAL_TRADE_ATTRIBUTION_STORE_V01.md
```
