# Company research reliability contracts — 2026-10-20

Scope: audit findings 1, 2, 3 and 7. This is a local implementation contract, not evidence of live-provider accuracy or model quality.

## Source identity and time

Financial health packets, announcement lists and lockup calendars are wrapped at the production source-plan boundary in `company-native-request.v1`. `requested_subject` records the actual adapter argument; `identity_basis=ADAPTER_REQUEST_CONTRACT_NOT_PROVIDER_IDENTITY` explicitly does not claim an independent provider-return identity. The original adapter payload is retained. Known identity fields supplied by upstream data are checked before the adapter can discard them; conflicting identity fails the source. The new financial `strict` keyword defaults to false, preserving existing callers.

An empty native collection remains MISSING. Malformed/provider-failed sources remain ERROR and their payload is excluded from model context. Financial reporting periods, announcement disclosure dates and lockup event dates remain in the payload; they are not relabelled as a common source publication time. Past cutoffs still use only archived sources.

## Persistence

Model metadata is validated before inserting a run or calling a model. Missing or blank provider means generic compatible `api`, not a claim about a particular vendor. Invalid metadata is rejected. Every stored terminal record is validated against its frozen bundle. FAILED/CANCELLED retain only metadata and completed-stage count, never stages or a completed-result hash.

A terminal-write exception triggers strict readback before fallback. An identical committed terminal is accepted as acknowledgement recovery. Other terminal/owner conflicts are not overwritten. If persistence and recovery both fail, there is no successful-completion receipt; an unresolved RUNNING record is not represented as currently executing or successful.

## Read-only history

- Existing `GET /api/company-research/runs` remains the strict legacy latest-50 array.
- `GET /api/company-research/history?market=A&symbol=600519&limit=50` filters the subject before limiting. Pass the returned opaque `next_cursor` to continue. The cursor binds the subject, descending row position and initial high-water mark. New rows do not repeat/shift older pages.
- Each page contains `records`, `diagnostics`, `unassigned_corrupt_count`, `next_cursor`. Records undergo full bundle/result/stage validation. A damaged item is only a `CORRUPTED_OR_UNSUPPORTED` diagnostic, never a report. Unassignable rows, including invalid/noncanonical identities and duplicate-key JSON ambiguity, are separately disclosed using the production identity contract. SQL/schema failure still fails the complete request closed.
- `GET /api/company-research/runs/{run_id}?market=A&symbol=600519` strictly validates the exact run and requested subject.
- `GET /api/company-research/diagnostics` explicitly scans read-only integrity categories and returns counts, without model text or credentials. No diagnostic endpoint repairs data.

The panel provides older-page access and distinguishes empty history, unreadable history and damaged records. Subject/date changes and unmount cancel or invalidate pending reads. Opening saved evidence never refetches native sources or calls a model.

## Legacy recovery boundary

No schema migration, record deletion, provider patch, bundle rewrite or rehash is performed. Valid legacy records retain their bytes, IDs and hashes. A completed record's provider participates in its result hash, so filling a blank string is not an integrity-preserving repair. Unsupported/corrupt records remain intact and visibly diagnostic. A database structural failure remains fail-closed.

Any future recovery must separately preview affected records, use a consistent backup (including SQLite WAL state where relevant), obtain authorization for real archives, and preserve original bytes and a versioned recovery trail. Old ERROR source bundles are not converted in place into AVAILABLE sources. A user-triggered new capture produces a new bundle; no automatic paid-model reruns are introduced.
