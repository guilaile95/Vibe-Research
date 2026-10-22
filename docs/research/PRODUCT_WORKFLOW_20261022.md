# Product workflow repair acceptance — 2026-10-22

## Scope and baseline

This record covers bounded failure-state, navigation-continuity and saved-result provenance repairs. It does not authorize deployment, provider/model calls, real holdings/history processing, automated trading or broader workflow redesign.

Baseline: `feature/research-system-v01` at `ad267801e2a3295a50e1d028e400d9ec784f4fdd` (PR #409). The baseline [CI](https://github.com/guilaile95/Vibe-Research/actions/runs/39642993682) and [Windows launcher smoke](https://github.com/guilaile95/Vibe-Research/actions/runs/39642993700) completed successfully. Historical open Drafts are not reopened by this batch.

Baseline static observations are not browser acceptance:

- Today attention-list links and Watchlist candidate links omit their list return context; Today has a shared empty-list message without an explicit list-read-error state.
- Hotlist AI sections contain normal-result fallback text and numeric RSS coverage without the required unanalysed-state explanation.
- Saved notes preserve the existing optional single-security `research` object; a daily/macro generation must not invent a security code to fit it.

Baseline local frontend checks: 2,057 passed, zero failed, one explicitly conditional synthetic saved-research replay skipped; TypeScript/Vite build passed with the existing large-chunk warning. The replay requires a backend-produced `VR_SAVED_REPLAY_FILE`; its conditional frontend skip is not replay acceptance. The exact final-head suites and backend-produced replay remain separate gates below.

## Three bounded journeys

| Journey | Before-change evidence | Required acceptance |
| --- | --- | --- |
| Known A-share research | Inspect submitted StockData identity and candidate-entry placement | A valid submitted A-share remains researchable when quote/valuation fail; drafts, invalid input and stale requests cannot replace the active identity |
| Followed-security change | Inspect Today/Watchlist links and existing candidate/evidence return helper | List → candidate → evidence → save → product return reaches the originating list with a safe anchor; browser navigation cannot bypass unsaved protection |
| Continue during a fault | Inspect hotlist AI/list failure rendering and saved-note serialization | Explicit unavailable/error/old-result states; retain saved evidence identity and body across close/reopen/export/import without presenting failure as an empty business result |

## Contract and evidence matrix

Status is pending until a named test and exact reviewed source establish it. Unit contracts, synthetic browser interaction, source/provider verification and natural-use evidence are different evidence classes.

| Area | Required cases | Evidence gate |
| --- | --- | --- |
| Hotlist AI | Success nonempty/empty, returned ERROR, network/parse error, old success after failed retry, slow/late results | State contracts and desktop/390px synthetic browser |
| Attention list | Loading, genuine empty, read failure, stale list, retry, late response ownership | State contracts and desktop/390px synthetic browser |
| RSS | Disabled, enabled with zero actual inputs, actual nonzero input set; no budget-algorithm change | Producer contracts and truthful UI coverage |
| Return navigation | Today/Watchlist/StockData origins, candidate/evidence/save/return; unsubmitted/cross-security identity | Helper contracts and actual full-route synthetic browser |
| Return safety | Absolute/protocol-relative URLs, backslashes, encoded variants, duplicate/malformed parameters; deterministic internal fallback | Negative URL contracts, no external navigation or identity promotion |
| Unsaved protection | Product return, Back/Forward, cancelled navigation and continued edits | Existing guards plus affected browser regressions |
| Saved AI provenance | Original result identity/reference, trading date, generation vs save time, cutoff, model and input gaps; unknown remains unknown | Serialization/parser contracts and reload/export/clean-import journey |
| Notes compatibility | Legacy notes/backups, existing stock research, mixed generations, duplicate IDs, 200-entry limit, corrupt data and quota failures | Synthetic fixtures; failure preserves prior records |
| Source identity | Manifest exactly matches actual model input; source title/time/URL/identity and omitted/truncated reasons | Producer-to-consumer tests, unsafe-URL tests, bounded UI |
| Missing originals | Saved snapshot remains tied to original identity, never silently redirects to latest | Unavailable-original regression |
| Integration | All accepted patches, shared-file resolution and no weakened production guards | Independent review of final combined diff |
| Final CI | Frontend full suite/build, runtime, Linux/Windows full offline backend, all existing and new relevant browsers | Exact published HEAD; merge-tree identity verified |
| Stable delivery | Ordinary merge only after acceptance; final stable CI and clean source identity | Exact post-merge HEAD |

## Isolation and compatibility boundaries

Use only fresh synthetic stores and controlled fixtures. The existing `tools/validation_environment.py` and backend `conftest.py` reset private-path overrides and credentials before application imports. This storage policy is not a network sandbox. Browser fixtures must deny unexpected external requests and retain request-audit evidence; genuine backend/provider calls require their own explicit controlled boundary. Reuse the existing CI jobs rather than changing production access guards or skipping failed assertions.

Old records are read without backfilling unknown model/date/source fields or changing their bodies and identities. New optional metadata must be bounded and validated through the existing note save/import/export path. New-version backup round-trips are tested separately from old-client behavior: an old client may discard new metadata, so lossless two-way downgrade compatibility is not promised. Code rollback is not restoration of private data; no migration or automatic cleanup is included.

## Results and remaining evidence

Implementation and final integration results will be recorded here only after verification. The baseline is not the final deliverable.

Real provider/source reliability, real model quality, natural next-day continuation, deployed version and sustained product value are **NOT_EVALUATED** in this batch. Synthetic green tests must not activate Product Reality Day 1 or be described as demonstrated research-efficiency improvement.
