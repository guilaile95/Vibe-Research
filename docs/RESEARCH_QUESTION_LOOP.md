# Local question checks

## Scope and authority

A question check connects why a security is being researched, selected material,
a bounded comparison, the user's judgement, and later rounds on the same question.
It is a browser-local research record, not Evidence, Campaign, a Formal Decision,
a recommendation, or a trade. No model call is necessary to complete this path.
Exploratory chat remains a separate path: its tool statuses do not preserve all
returned tool text and do not establish a closed historical replay.

Existing MyReports search and page reading remain the document interface. Search
misses are not proof that a company has not disclosed something. A link, title,
metadata hash, or successful request alone does not establish full-text coverage.
Page excerpts retain their actual read range and limitations. A user transcription
of a financial operand is explicitly different from automatic extraction or
independent verification.

## Storage boundaries

The new research domain uses its own IndexedDB database, not the old `vr-notes`
array. Legacy records are not automatically moved or deleted. Explicit import
reads the legacy source and preserves it. A later old-client change is not an
instruction to overwrite a new question's head.

Rounds are immutable. Appending checks expected revision and head, inserts the
round, updates the question's reviewed-material baseline, and records the
operation identity in one transaction. A stale tab must retain its draft rather
than silently changing its parent. The same operation can be retried; a different
payload cannot reuse that identity. Only transaction completion reports success.

An export is a complete versioned backup, not a substitute for normal use.
Import validates complete chains before committing; capacity must not truncate a
parent away from its children. Browser storage remains subject to quota, privacy
mode, user deletion and browser durability limits. This is not cross-device sync
or a promise of permanent retention. Closing older new-domain connections is
necessary during schema upgrades; a blocked upgrade must produce a recoverable
error rather than an endless spinner.

## Acceptance and evidence boundaries

Required deterministic checks include wrong security, report period, metric,
currency/unit, consolidation scope and forecast/actual mode. Unknown or mismatched
comparison dimensions fail closed. Normalized loss ranges preserve negative
bounds. Original and revised forecasts are not audited actual results.

The built UI acceptance must demonstrate one question through T0 save, close and
reopen, T1 continuation, and viewing the unchanged T0. Separate storage checks
exercise concurrent connections, rollback/abort, upgrade blocking, legacy-client
isolation, complete export/import restoration and budget failures. Synthetic
fixtures are labelled as such, and must not be presented as natural user use,
provider completeness, live-model accuracy, strict point-in-time data, or economic
value. CI artifacts describe only the exact build and scenarios executed.

The discovery-to-candidate handoff retains a bounded (16 KiB) non-authoritative
snapshot of the original card's observations, reasons, source references and
times. Missing handoff state is explicit; a strategy label is not reconstructed
as the original discovery evidence. Basic saving requires a question and either
a short judgement or a next question. Detailed calculation is optional, and an
unrecorded limitation is labelled as unrecorded rather than invented.

The first local implementation validates the entire bounded store per operation:
16 MiB serialized application budget and 2 MiB per round. It is not indexed
pagination or an unbounded history engine. Native browser fault injection tests
transaction rollback, not actual disk exhaustion or power-loss durability.

The public forecast-revision and transaction-stage examples are semantic test
inputs. Their cited documents are not a fixed point-in-time archive unless raw
bytes, hashes, publication availability and the release boundary are independently
established. A copied numerical answer key is not independent human adjudication.

## Non-scope

No automatic backend migration, new paid provider, background full-market
collection, deployment change, automatic formal-state update, or inferred Product
Reality Day 1. Natural use is a separate observation after engineering acceptance.
