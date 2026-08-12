# P0-TCR1 Trade Campaign Reconciliation State Core v0.1

## Product question

> For an already-recorded Manual Trade, given current formal attribution
> coverage, is it explicitly allocated to a Campaign? If not, must it enter
> UNALLOCATED / RECONCILIATION REQUIRED?

## Anti-rewheel

```text
EXISTING_FORMAL_TRADE_RECONCILIATION_AUTHORITY = NO
P0_TB1_REUSED = YES
```

| Surface | Why not TCR1 |
| --- | --- |
| North Star §20 | Product law only |
| `formal_trade_attribution` (P0-TB1) | Formal Decision ↔ Trade attribution, not reconciliation-state |
| Fact Lake reconciliation | Dataset/source disagreement, not trade-campaign |
| Position Reality PRE_VIBE / LEGACY_POSITION_OPENING | Legacy holdings, not Trade Ledger records |

TB1 is reused, not reimplemented.

## Role

```text
TCR1_ROLE = TRADE_CAMPAIGN_RECONCILIATION_STATE_AUTHORITY
```

Does **not** create campaigns, decisions, attributions, POST-ENTRY bindings,
or synthetic PRE-VIBE BUY records.

## Coverage vs empty set

```text
EMPTY_LIST_ALONE_PROVES_UNALLOCATED = NO
COMPLETE_EMPTY_SET_PROVES_UNALLOCATED = YES
```

`attribution_coverage` is an explicit upstream claim: `COMPLETE` /
`UNKNOWN` / `NOT_EVALUATED` / `ERROR`, with non-empty authority refs.

Only `COMPLETE` + validated empty match set proves `UNALLOCATED` /
`REQUIRED`.

## Core matrix

| Trade | Coverage | TB1 match | allocation / reconciliation |
| --- | --- | --- | --- |
| current full/partial | COMPLETE | yes, cross-anchor OK | ALLOCATED / NOT_REQUIRED |
| current full/partial | COMPLETE | none | UNALLOCATED / REQUIRED |
| current executed | UNKNOWN | — | UNKNOWN / UNKNOWN |
| any | NOT_EVALUATED | — | NOT_EVALUATED |
| any | ERROR | — | ERROR |
| not_executed | known policy | — | NOT_APPLICABLE |
| voided | known policy | — | NOT_APPLICABLE |

Unknown well-formed policy never applies v0.1 UNALLOCATED / NOT_APPLICABLE
packet semantics.

## TB1 reuse

When coverage is `COMPLETE`, TCR1 calls:

- `validate_attribution_set`
- `attribution_for_trade`

TB1 errors fail closed. No skip / first-row / silent dedupe.

Matching attribution must cross-check trade_id, security_code, operation,
execution_status, executed_at, created_at against the current Trade witness.

```text
CAMPAIGN_ID_FROM_FORMAL_ATTRIBUTION = YES
CAMPAIGN_EXISTENCE_VERIFIED = NO
CAMPAIGN_STATUS_VERIFIED = NO
CAMPAIGN_INFERENCE = NO
```

## Explicit non-goals

FIFO, same-security inference, latest-campaign inference, AI inference,
POST-ENTRY binding engine, PRE-VIBE synthetic BUY, campaign_store I/O,
trade ledger I/O, Action Envelope, Risk Budget.

## Files

```text
backend/trade_campaign_reconciliation.py
backend/tests/test_trade_campaign_reconciliation.py
docs/p0/TRADE_CAMPAIGN_RECONCILIATION_V01.md
```
