# AI and Native Intel browser contract repair — 2026-10-24

Scope: PR #417, CI run 40091721958. Test-only repairs; production guards unchanged.

## Diagnosed failures

- Data-health job 120865596037: final-families asserted a model envelope without the server-dispatch revision.
- Intel job 120865596149: GH/HF deep-read and Wave 5 explicitly asserted revision absence; segmented review and campaign consent rejected the current exact generation-bearing envelope.
- The same strict-envelope mismatch affected extended-public research in smoke job 120865596053.
- Interest Filter installed an unsaved browser-only model and exposed no credential-status router. Its AI save was correctly stopped by generation preflight. The harness now saves a synthetic credential through the production CAS router in its temporary data directory and mirrors the returned revision.
- Native Intel expected the former full-failure wording. It now checks the precise error plus separate success/pending/failure counts. The late-tab fixture waits for both held route handlers rather than a response event that production cancellation may prevent.
- Settings recovery expected “connected” from login status. It now distinguishes authenticated/unprobed from legacy ready and checks the login control against authentication, not model availability. Calendar coverage assertions remain intact.

## Validation

- 60 targeted Node tests passed across credential generation, final families, extended research, segmented review, runtime status labels and settings fixtures.
- 3 backend tests passed: isolated Interest Filter credential/classification harness and credential model wire contracts. The harness test forbids real chat dispatch.
- Campaign consent production component build-only passed.
- Changed browser scripts passed Node syntax checks; `git diff --check` passed.
- Actual browser acceptance was not rerun locally because local browser execution is denied. Existing GitHub CI must establish rendered acceptance on the integrated repair head.
- No real model, secret, production account, publication or runtime deployment was used.
