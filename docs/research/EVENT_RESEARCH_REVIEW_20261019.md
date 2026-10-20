# Explicit event research review — 2026-10-19

## Contract

The existing Research Event Calendar stays a bounded, read-only projection of its four A-share event types. Users choose a Campaign with an existing canonical thesis binding, write an expectation for a particular observed event version, and explicitly create a `review_required` record. Users then choose existing same-subject Evidence records, explain their assessment, and confirm `support`, `refute`, or `insufficient`. Observing a publication never implies an expectation was met.

Persistence uses the existing `evidence_thesis.db` transaction/backup lifecycle. Two optional additive tables are initialized only by an explicit bind write: `event_research_reviews` holds immutable observations/expectations; `event_research_judgments` holds one immutable judgment per review. Reads never create or migrate tables. Canonical Campaign identity and immutable Campaign–thesis binding remain authoritative. Thesis, its revisions, Evidence, formal links, decisions and trades are never changed by this workflow.

Unique Campaign/thesis/event/fingerprint bindings make retries idempotent. A source-content change produces a distinct fingerprint and can receive a separate explicit review. Provider identity changes remain distinct events; the system does not infer that two publications are revisions of one another. The history selector retains Campaign reviews outside the currently displayed event window. Completed judgments retain the exact reviewed Evidence snapshots even if those Evidence records later change.

## Provenance and concurrency

Calendar HTTP responses include a signed observation receipt. Binding verifies the server-issued snapshot, event ID/type/hash and matching security; client-supplied source links or arbitrary snapshots cannot authorize a binding. This receipt attests to what was observed, **not current provider freshness or authentication**. Signing material is process-local, never persisted/configured as a credential, and expires after one hour. Restarting the process or sending a receipt to a different worker fails closed and requires refreshing the calendar. This minimal slice targets the existing single-worker local app; sticky/shared-worker receipt support is not implemented.

The immutable canonical Campaign binding selects the thesis. Thesis revision validation, unique binding insertion, Evidence edit-token validation and append-once judgment happen under the existing ledger write transaction. Stale revisions/evidence, conflicting expectation rewrites, duplicate judgment attempts and wrong-subject links fail closed. Judgment retries after a successful save return conflict and require rereading history, rather than rewriting a confirmed decision.

## UI

Expand “绑定研究预期 / 事件复核” in an existing event row, select a Campaign, write the expectation, then select evidence and record the assessment. “已绑定事件复核记录” provides history for Campaigns in the displayed universe, including records whose events have left the date window. Missing canonical bindings produce an explicit unavailable message. No Campaign is silently selected. A changed/unmounted Campaign selection ignores late responses.

Limits: the evidence picker displays up to 100 same-stock records; no document ingestion, inferred causality, push notification, model call, EDGAR source, trading change or automatic formal-thesis mutation. The history selector covers Campaigns returned by the existing calendar universe; the read API also supports an explicit Campaign ID.

## Verification

- Backend: `PYTHONPATH=backend python -m pytest -q backend/tests/test_research_event_review.py backend/tests/test_research_event_calendar.py backend/tests/test_evidence_thesis_service.py backend/tests/test_evidence_thesis_store.py` — 139 passed
- Frontend: focused event-review/calendar Node tests — 27 passed; TypeScript and production build passed
- New browser fixture: `frontend/tests/e2e/event-review.browser.mjs` covers explicit bind → evidence judgment → refresh, immutable completed controls and late Campaign context; fixture responses only, no provider calls
- Browser execution: **NOT_EVALUATED**. Installed Chromium failed before launch with `socket() failed: Operation not permitted`. No access bypass or alternate browser attempt after the denial

These local checks do not establish live-provider reliability, real-user acceptance, remote CI or deployment.
