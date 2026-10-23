# Account authority remediation, 2026-10-24

Scope: independent engineering audit P1-02, P1-05 and P2-01, based on `ddf7f9e7`.

## Contracts

- Both public trade-void routes use the existing same-database cascade command.
  The legacy route retains its trade-record response and 404/409 semantics.
  Recovery of pre-existing orphan corrections retains the original trade identity
  and void timestamp. History is soft-voided, never deleted.
- PA1 now labels incomplete selected-set cost accounting as `PARTIAL` with
  `MISSING_COST_BASIS`. Formal Outcome does not promote that partial amount to
  `MEASURED`: it returns `NOT_EVALUATED`, null P&L, and the reason. No account-wide
  cost allocation or synthetic zero cost is introduced.
- A newly frozen decision must have a review boundary strictly after its
  service-generated commit instant. Preview uses server time, not caller-supplied
  historical `as_of`. Existing exact replay retains its identity and remains
  permitted after expiry; this is not an import API for inventing past decisions.
- New full/partial execution timestamps more than five minutes ahead of server
  time are rejected. Existing future rows remain immutable. Current holdings and
  cash exclude effective future trades after corrections; tolerated clock-skew
  records do not become current prematurely.
- Canonical trade insertion validates the full chronological position derivation
  in its SQLite write transaction, including future records before they become
  current. Oversell and pre-ledger-boundary conflicts return HTTP 409 with
  `RECONCILIATION_REQUIRED` and persist nothing. Noncanonical historical fact
  recording remains supported. No lot allocation or opening balance is invented.

## Verification and limitations

The isolated offline domain regression contains 846 passing tests, including 20
new cross-domain cases: real FastAPI/SQLite legacy void, cascade rollback and
historical recovery, valid-account/incomplete-decision-cost Outcome, expiry and
exact replay, future holdings/cash, skew oversell, and concurrent sell insertion.
Historical test scenarios explicitly control server clocks rather than relying
on a synthetic evaluation date to authorize a new write.

A broader network-blocked run stopped at an unrelated local HTTP credential
fixture (`test_scheduled_api_fixture_success_and_secret_stays_local`): its socket
was deliberately blocked. That run is not full-suite certification. No real
accounts, holdings, provider network or model calls were used for acceptance.
Independent review and integrated CI are separate required gates.
