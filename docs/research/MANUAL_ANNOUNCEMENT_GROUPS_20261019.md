# Manual announcement-centered evidence relationships — 2026-10-19

## Delivered boundary

The Evidence detail screen supports explicit local grouping around an existing
announcement or financial-filing Evidence record. It does **not** automatically
merge Native Intel articles, infer equivalent events from titles, or assert a
canonical original-document identity. Persisted Native Intel source URLs and
observations remain untouched. This is a bounded manual alternative while verified
original-document identifiers are unavailable.

Every group, period/event scope and original/commentary/correction/amendment role
is `USER_DECLARED_UNVERIFIED`. Unknown roles stay unknown. The source-kind label
shows the Evidence record's registered type, not independently verified publisher
metadata. Grouping does not change Evidence classifications, thesis admission,
source trust, formal decisions, or strict-as-of eligibility.

- All members must be existing, non-deleted records for the same stock
- Different titles may be linked only by explicit declaration; same titles never
  cause a merge, and event period is a required declaration rather than inferred
- A member cannot belong to overlapping groups; no automatic consolidation
- Corrections/amendments link to a retained member; missing targets and cycles fail
- Group identity, subject and period cannot be changed by an append
- Existing members and relationship assertions are retained; all revisions store
  exact Evidence snapshots. The live Evidence remains separately accessible
- A transaction checks member edit tokens and expected group revision; concurrent
  updates fail closed. An identical request ID/payload retry returns its original
  result; reusing that ID for different content fails
- GET context never creates tables or relationships. Explicit POST owns writes
- The UI shows up to 200 current same-stock candidates and states truncation

Persistence uses the existing Evidence database transaction and backup mechanism,
with an additive `research_announcement_group_revisions` table. No new provider,
network fetch, credentials, dependency, model call or trading action is introduced.

## Ownership change: NOT_IMPLEMENTED_PREREQUISITE_MISSING

The inspected Native Intel item projection contains titles, summaries, source
URLs, timestamps and observations. It does not provide verified SEC 13D/13G/Form 4
ownership entities or accession-linked structured ownership changes.
`filing_evidence.py` supports local user-text registration for 10-K, 10-Q, 8-K,
their amendments and generic announcements, always unverified. It neither ingests
13D/13G/Form 4 nor validates beneficial owner, issuer, transaction dates, ownership
units, amendment lineage or transaction meaning.

A real ownership-change card therefore remains unimplemented. It requires an
approved authoritative source adapter with stable filing/accession identity,
issuer and holder identity, filed/event dates, amendment links, and validated
ownership/transaction semantics. Pasted text, an inferred shareholder name or a
manual quantity input is not substituted for that missing source. No contact email
or provider setup was invented. edgartools/AKShare are conceptual references only;
no code or dependencies were copied.

## Validation

- Backend focused + filing/evidence regressions: 80 passed in isolated offline
  network namespace using the dependency-equipped project Python
- Frontend build: TypeScript + Vite passed; existing large-chunk warning remains
- Frontend targeted tests: 12 passed. Actual component execution tests cover explicit-save-only behavior, single-flight
  submission, visible conflict without auto retry, retained revision rendering,
  unsafe source links, unknown roles, late read rejection, and authenticated GET/POST
  through the shared API request client
- Browser runtime acceptance was not performed: the previously established browser
  OS restriction was respected and not retried. Component tests and build are not
  browser or real-market acceptance

Scope stops at local commit and integration; no push, PR, merge or deployment.
