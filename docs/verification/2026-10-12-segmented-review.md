# Segmented short-line and weekly market reviews

## User flow

DailyReview current and selected history each expose **分段复盘与周报**.
Choose daily or weekly, explicitly inspect the material preview, then manually
start. The preview shows the exact calendar dates, material identity, sources,
missing inputs and maximum model call budget (daily six, weekly four). Page or
history loads only read saved versions; they never generate or collect data.

Daily sections are sentiment, capital, theme, Dragon-Tiger and leader, followed by
synthesis. Weekly sections are emotion trend, theme rotation and condition-result
review, followed by synthesis. Prior-week emotion context may be included; weekly
condition outcomes must have target dates in the selected week through the selected
end date. No private portfolio, trade records or user-written condition reasons
enter the model context. Personal trading statistics remain a separate local view.

The existing chat runtime, model configuration, transport and disconnect signal
are reused. Each section starts a fresh session and sees only its scoped finite
snapshot. Summary sees only sections without detected audit problems, along with
their original evidence; prior output remains untrusted data. No second AI runtime,
autonomous scheduler, hidden retry or automatically saved tomorrow condition is
introduced. Leaving the page retains the in-memory task owner; explicit cancel
aborts the request, stops future calls and prevents a commit after cancellation is
observed. Late responses cannot replace newer UI ownership.

## Evidence and status

The material bundle is frozen before the first call. POST requires the preview's
bundle hash; changed inputs require another preview rather than silently consuming
model budget against new evidence. A generation ID deduplicates retries and refuses
conflicting reuse. Simultaneous runs are bounded to two.

Archived data is `CURRENT_STORED_POSTHOC`, `point_in_time_claim=NONE`, with no
canonical authority promotion. Business date is distinct from historical
knowledge availability. Source identities, paths, values (including explicit
nulls), units and FIXTURE/ACQUIRED/UNCLASSIFIED origin labels are retained.
Synthetic cases do not count as market acquisition. Omission counts reflect
whole rows excluded by the finite input budget. Weekly input is allocated evenly
per date with date-specific omission diagnostics; dense earlier sessions cannot
erase later sessions.

Generation status and support checks are independent. Unknown evidence references,
literal arithmetic contradictions and unbound numeric tokens mark a section
`requires_review`; those sections do not feed synthesis. The numeric check is
conservative and incomplete, not a proof of number-to-claim semantics. Even a
section without detected problems says `no_detected_issue_not_verified` and
`fact_verification=NOT_PERFORMED`. Missing data and missing conditions remain
explicit gaps. Incomplete streams or cancelled runs do not save a version.

## Persistence and limits

Versions append to `shortline_review_versions` in the existing review database.
There is no version overwrite/delete route or migration of the existing v1/v2 AI
results. A transaction rechecks cancellation immediately before commit. Readback
checks the payload hash, exact bundle, stage scope and recomputed audits. Read-only
history inspection loads bounded stable database bytes into private SQLite memory,
refusing active WAL/rollback data; it creates no source WAL/SHM files.

Limits: ten calendar sessions, 160 evidence rows and 32 KiB per section, 256 KiB
bundle and 256 KiB per model user-message including synthesis inputs, 12,000 output characters per section and 60,000 total, 180 seconds per
section and 720 seconds overall, one call per populated section, no retries,
1 MiB saved version, 30 versions per date/mode list. Runtime cancellation is signaled
at the deadline; existing finite transport timeouts bound cancellation response
when an underlying socket cannot be interrupted immediately.

## Data dependencies and collection boundary

- P2 `query_shortline_research`: daily/cohort inputs with exact selected date.
- P3 `query_theme_research`: exact-date theme tree/firstboards; provider editorial
  attribution is not company confirmation. Complete and partial statuses remain
  distinct; current tags never backfill old dates.
- Existing saved daily review supplies capital activity and indices.
- Supplement raw adapters cover Eastmoney market margin `RPTA_RZRQ_LSHJ`, industry
  main-money flow and `RPT_DAILYBILLBOARD_DETAILSNEW`. Industry snapshots require a
  source `f124` timestamp matching the business date. Missing numeric fields remain
  null. Each capture is bounded to the first 100 records; incomplete pages are
  partial samples and no cross-record Dragon-Tiger summation is inferred.

The internal manual collector is disabled unless
`VR_SHORTLINE_REVIEW_CAPTURE_ENABLED=1` and an existing writable FactLake is
configured. No HTTP/page/generation path activates it. It uses fixed provider
endpoints through existing Eastmoney transport, never client-provided URLs or
credentials. Receipt ordering compares parsed UTC instants, with same-instant conflict rejection.
Each of three supplemental listings has a 4 MiB aggregate raw-read cap, and each
selected replay a 4 MiB cap: at most 12 MiB scanning plus 12 MiB selected replay.
The public bounded read checks its cap before blob I/O. Failed normalizations retain
the original raw receipt as invalid rather than erasing the response.
Activation is a separate operational decision; no real provider or
model calls were made for implementation tests. Tests use synthetic input and model
stubs, and cannot establish trading-hours or provider compatibility acceptance.

## Verification snapshot

Focused offline tests cover append/restore, immutable source binding, explicit
cancellation, incomplete streams, strict whole transport guards, real SQLite
read-only checks, real FactLake valid and failed raw receipt persistence, and
production JSX malformed-preview/list recovery. Three cumulative integration tests
exercise actual P2/P3 services and supplement replay after those dependencies are
merged into the candidate; they are explicitly skipped on the isolated P5 base.
An independent temporary overlay of cumulative 4444aa2 plus the bounded raw-read
fix passed all three with zero skips, including same-second receipt ordering.
These dependency skips must be zero at final release acceptance. Browser and live
market acceptance are separate; this implementation has not run either.
