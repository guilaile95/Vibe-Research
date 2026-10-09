# Evidence edit preconditions (2026-10-09)

## Contract and rollout

Evidence reads (GET/list), creation and successful updates return `edit_token`.
The server hashes an explicit set of persisted Evidence fields with stable JSON
and SHA-256, prefixed `evidence-edit.v1:`. The token is a content precondition,
not a credential, an audit revision or a retrievable history reference.

- PUT `/api/evidence/{id}` requires `expected_edit_token` in its JSON body
- DELETE `/api/evidence/{id}` keeps `confirm=true` and requires
  `expected_edit_token` in its query parameters
- Direct `update_evidence` service callers supply that field in their data;
  `soft_delete_evidence` callers supply the third argument
- Missing, non-string or malformed tokens fail closed with 422 (matching the
  required Thesis revision input convention); stale tokens return 409
- Missing/already-deleted records retain 404 semantics; no conflict response
  supplies a replacement token for automatic retry

This intentionally stops old clients from doing unconditional writes. Deploy the
frontend and backend together, reload old tabs, and update external automation
before it resumes writes. Read the Evidence, capture the returned token with the
content being reviewed, and send that exact token with the intended change.
After 409, read and review the latest content before creating a new edit; do not
fetch a fresh token and silently retry an old complete form. Old read/create
clients continue working. No database migration, new ORM or history table is
needed. In-repository production mutation callers are the Evidence router and
EvidenceDetail client; regression/acceptance clients were migrated explicitly.

## Atomicity and UI

Comparison runs inside the existing `BEGIN IMMEDIATE` write transaction, before
any Evidence write or dependent Thesis revision. A conflict rolls back without
business mutation. Current successful edits/deletes retain the prior mutable
Thesis cascade and confirmed/frozen snapshot protection.

The editor captures its token when editing begins. Conflicts keep every local
form value, show latest content separately, and block further submission until
the user explicitly confirms discarding the draft and loads that version. The
latest-content request can fail without losing the draft. There is no automatic
retry, merge, force overwrite or AI call. Users may copy their draft before
discarding it, then make a new reviewed edit; that edit is checked again.

## Boundaries

All persisted Evidence fields participate, including identity, nullable source
fields, timestamps and deletion state. Thus content changes are detected even
under a fixed clock. Returned presentation metadata and the token itself do not
participate. No timestamp parsing/reformatting occurs during hashing: stored
values are compared consistently, and null remains distinct from an empty string.

A soft-deleted row cannot be edited even with its newly returned deletion token.
Recreating an Evidence through the public create operation generates a new ID,
so the old token cannot authorize it. Restoring a backup or directly restoring
all persisted fields to the identical original values yields the identical token
(ABA). This is deliberately a content-equality guard, not a monotonic event
counter or protection against administrative database replacement. A future
strict audit requirement needs separately designed revision/history storage.

## Verification scope

An offline negative control using baseline `9eb35c2` reproduced two successful
saves with stale B overwriting A's claim. New synthetic tests cover stale update
and delete, unchanged Evidence and Thesis state after rejection, fixed timestamps,
malformed/missing/other-record tokens, lost-response replay, fresh update/delete,
and two independent SQLite connections with the Python mutex bypassed. Existing
formal lifecycle, concurrency, temporal and continuity acceptance tests remain
part of the regression selection.

The deterministic two-page browser harness is
`frontend/tests/e2e/evidence-edit-conflict.browser.mjs`. Browser execution in the
implementation environment is denied and was not attempted; runtime browser
acceptance must run in the permitted CI environment before claiming it passed.
No real provider, model, account or production database was exercised.
