# Whole-project audit repair candidate — 2026-10-20

This record describes the bounded implementation following the 19-finding review.
It is not a deployment, live-provider/model-quality, or natural-use acceptance.
The prior reviewed baseline is PR #409 head `8c095246386a5cddff1f8ba8f4894a9086094b12`
(tree `bde51765e25671c4160bae89732b10a101336efc`). Exact publication and CI results
belong in that PR's dated evidence, not a guessed stable version in this document.

## Repair boundaries

- Shared test environment policy isolates inherited per-store overrides, platform
  home roots and provider configuration before application collection; both Native
  Intel automatic tasks are disabled. This policy is not an OS/network sandbox.
- Deep-read fetch validates each public unicast destination and redirect, pins the
  checked address through HTTP/TLS connection, retains hostname certificate checks
  and bounds transfer/handshake time. Unsupported proxy routing fails closed rather
  than bypassing configured routing. No real internal service was probed.
- Agent Runtime checks exact loopback Host, browser Origin/fetch metadata and JSON
  mutation input before side effects. Backend transport ignores inherited proxies
  and rejects redirects. This is not authentication against a malicious OS process.
- Credential v2 generations serialize saves and make clear a monotone barrier.
  Unconfigured tombstones contain no secret. Client intent owns completion and
  cannot borrow a revision observed after an older intent; submit-time checks reject
  stale browser configuration. Client-only revision is excluded from strict model
  wire schemas. Clearing the application does not revoke a provider key or undo an
  already-sent request. Store locking assumes one backend writer process; browser
  physical storage across old/dormant tabs is not an atomic erasure guarantee.
- Selected trade corrections make PA1/actual outcome explicitly unavailable with
  a reconciliation reason; they are not silently recomputed under old provenance.
  Unrelated exact selections remain available. Saved snapshots retain their bytes
  and gain outer current-applicability information. Actual historical outcomes
  enforce execution, recording and attribution cutoffs; non-reconstructible later
  correction/void states remain unmeasured, not zero.
- Effective correction prices must be positive; fees may be zero. Cash insertion
  requires an account opening in the same write transaction. Legacy inconsistent
  states are diagnosed without rewriting history.
- Stock and sector pagination pin immutable RDP generations and validate every
  page's identity/provenance. Financial report currency is distinct from quote
  currency; unsupported amount scale is explicitly unverified. Valid zero profit
  is preserved rather than treated as missing.
- Chat reads do not delete corrupt originals; oversized complete answers remain
  visible/exportable without erasing saved history. Evidence/revision responses
  belong to current query identity. Both daily quote views disclose stale, failed,
  missing and unknown/future provider time without adding polling.
- Late report unlink failure restores a manageable archive or reports recovery
  required; no false deletion success. Fulltext removed before that failure is
  honestly NOT_INDEXED. Thread locking and external modification detection do not
  claim multi-process filesystem/SQLite atomicity.
- Only complete translations enter reusable success cache; partial fallback is
  explicit and retry remains manual. Analysis counts participate in the same
  deterministic fingerprint as the prompt. Cache versions preserve old artifacts
  rather than deleting or automatically re-running them.

## Evidence and release gates

Regression coverage includes original synthetic counterexamples, normal controls,
actual component/storage handlers, real temporary SQLite/RDP import/query paths,
HTTP handler negatives, deterministic concurrency and strict wire-schema checks.
The 1001-security/default-1000-page RDP rotation case passed in the targeted run.
Independent reviewers checked the isolation, formal authority, data/recovery,
frontend and security deltas; review-discovered address, TLS ownership, credential
ordering and wire-compatibility edges received additional corrections/tests.

Existing browser scenarios were extended for credential save/clear and daily
quotes. A dedicated `test:e2e:workflow-recovery` scenario is wired to CI with
artifacts. Local Chromium could not create its OS singleton socket; no local
browser pass is claimed. Actual Windows and browser acceptance must be established
on the final publication, not inherited from the baseline's green CI. Full offline
backend/frontend/runtime selection remains enabled; no failing test is waived to
obtain a green result.

The Windows parent-exits/descendant-survives cleanup concern remains a separate
unconfirmed candidate, not one of the 19 proven repairs. No production process was
used to test it. Merge and deployment are separate states; deployment, real sources,
real model calls and modification of real historical data are outside this repair
candidate's executed validation.
