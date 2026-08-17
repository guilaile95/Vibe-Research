# P0-ET1 Anti-Rewheel Inventory

## Scope and boundary

ET1 adds a named producer for Evidence Effective-Time Authority and a durable
readback/product surface. It does not wire the producer into Decision Commit,
Material Change, CF1/Outcome, or DCH1. The existing EC1 projection remains a
consumer-ready deterministic core, not an ET1 persistence target.

## Existing authorities inspected

### Existing Evidence ledger (`evidence_thesis_store`)

- `evidence_records` is the canonical Evidence body and identity store.
- Its stable identity is the 32-character hexadecimal `id`, with subject
  identity (`subject_type`, `subject_id`) held on the same row.
- Existing temporal fields are `source_date` (date-only), `accessed_at`,
  `created_at`, and `updated_at`.
- `source_date` is not a canonical source publication instant. `accessed_at`
  is retrieval/access time. `created_at` is record creation time. None may be
  promoted to `effective_at`.
- Existing CRUD and thesis-link behavior must remain unchanged, including
  revision generation and confirmed/frozen content locks.

### Existing decision trace (`decision_trace_store`)

- `evidence_items` stores `observed_at` and `created_at`, plus a source-ref
  payload, but has no durable source publication or event occurrence authority
  bound to the Formal Evidence record identity.
- The trace service treats these values as observation/archive provenance. ET1
  will not reinterpret them as effective time.

### Existing EC1 projection (`decision_evidence_delta_projection`)

- `NormalizedEvidenceItem.effective_at` is the only time value used for
  `NEW_AFTER_DECISION` classification.
- `retrieved_at` is retained for provenance only; it is never a substitute for
  `effective_at`.
- Missing effective time is an explicit `UNKNOWN` temporal state and is safe to
  project as unknown rather than guessed.
- ET1 reuses this value-object contract for its EC1-safe normalized output; it
  does not create a parallel delta classifier.

### Existing source/data metadata

- The repository data contracts distinguish `published_at`, `observed_at`,
  `effective_at`, and `fetched_at` on provider observations.
- Those provider observations are not currently linked to the Formal Evidence
  ledger's `evidence_records.id` through a durable source/event identity in the
  ET1 base. They therefore cannot be silently treated as authority for an
  Evidence record.

## Reuse decision

`REUSE` the existing Evidence ledger for Evidence identity, subject identity,
and body readback. `EXTEND` that same SQLite database with one append-only
temporal provenance table because the current `evidence_records` schema cannot
persist source publication/event occurrence metadata without changing the
stable Evidence body contract.

No second Evidence body store is introduced. The companion rows contain only
the immutable factual temporal intake and its identity references; they do not
copy claim, source title, URL, classification, confidence, or any other
Evidence body field.

## ET1 temporal rules to implement

The producer distinguishes:

- `SOURCE_PUBLISHED_AT` — authoritative only with a non-empty source identity.
- `EVENT_OCCURRED_AT` — authoritative only with a non-empty event identity.
- `OBSERVED_AT` — observation time only.
- `CREATED_AT` — record time only.
- `INGESTED_AT` — ingestion/fetch time only.
- `EFFECTIVE_AT` — derived only from the two real source/event authorities.

Exactly one valid source/event authority can produce `PROVEN`. Neither, with
only observation/record/ingestion timestamps, produces `UNPROVEN`. Conflicting
source and event authorities produce `ERROR`; there is no winner. Malformed
timestamps fail closed. A proven effective time after `evaluation_as_of` is not
emitted as a currently usable EC1 evaluation, even though the underlying
authority remains visible for audit.

The caller can submit factual source/event/observation metadata only. The
caller cannot submit `effective_at`, `temporal_state`, `temporal_basis`,
`authority_refs`, `evaluation`, EC1 state, or `NEW_AFTER_DECISION`; all of those
are producer-derived or absent from the public intake model.

## Durable schema contract

The companion table is append-only and identity-bound:

- primary key: immutable intake row id;
- foreign key: `evidence_id -> evidence_records(id)`;
- unique payload hash for idempotent re-intake;
- index by `evidence_id`;
- raw factual temporal fields plus source/event identity references;
- no update/delete path;
- readback aggregates all rows for one Evidence identity and fails closed on
  conflicting authority rows.

This preserves historical provenance while keeping the existing Evidence CRUD
and thesis revision contract untouched.

## Product surface and verification

- API: factual temporal intake plus `GET /api/evidence/{id}/temporal-authority`.
- UI: existing Evidence detail page displays status, basis, effective time,
  reason, and the explicit statement that observed time is not effective time;
  intake controls submit factual metadata only.
- Tests cover ET1 contract cases A–M, existing EC1 regression, API rejection of
  caller-declared authority, durable refresh/readback, and isolated real
  browser execution against a temporary DB.

## Explicit non-goals

No Decision Commit fan-in, Material Change activation, `NEW_AFTER_DECISION`
production fan-in, AI dating, hard-risk/risk-budget work, portfolio accounting,
broker integration, CF1 price/outcome changes, DCH1 changes, workflow changes,
or schema redesign beyond the minimal temporal provenance companion table.
