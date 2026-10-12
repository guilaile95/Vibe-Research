# Next-session market-condition journal, 2026-10-12

## Scope and upstream comparison

Source reviewed: [Simon verification.ts](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/orchestrator/src/finance/shortline/verification.ts), [metric registry](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/orchestrator/src/finance/shortline/verify_metrics.ts), and [managed-write guard](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/orchestrator/src/service.ts).

Adopts explicit prior-time market conditions, next-session reconciliation, missing-not-failed results, historical direction frequency, and covered-subset excess. The upstream supports eight metrics, legacy imports, generic ledger integration, and daily endpoint collection. This slice deliberately supports only the two canonical local metrics whose units already match: limit-up count (5-count flat tolerance) and failed-board rate (0–1 ratio, 0.05 flat tolerance). No guessed mappings for promotion, theme concentration, or deep-loss fields.

Differences from upstream:

- Unknown exchange calendar blocks every write. No weekday fallback or create/edit fail-open.
- The same sealed write path handles all additions, updates, and removal; there is no generic ledger endpoint, import timestamp, or agent write tool.
- Prior value, historical pair counts, frequency and evidence are frozen when the user saves. Later backfills cannot improve an earlier condition's baseline.
- Reuses the validated offline calendar and existing final fact store; does not collect data or open existing fact publication/ingestion gates.

The signal ledger archives authoritative decision-pipeline evidence; trade ledger records manual transactions; historical signal validation studies price signals; research-event calendar records events. None is a user-authored next-session market-condition journal. Their authority and storage are unchanged.

## Usable entry and authority

The existing Today / DailyReview page contains **明日验证 · 事前条件**. Users choose a review session, select a direction and optional reason, and explicitly save the whole evening. Removing both conditions then saving is an explicit clear operation, allowed only before sealing. Re-reading discards the current unsaved form. Results, timestamps, sample counts and coverage are shown below the form.

The dedicated GET and PUT `/api/next-day-verification/{day}` endpoints inherit the application's host/origin boundary. PUT accepts only revision and at most two unique metric conditions. Server timestamps are not accepted from callers. No schedule, model, provider call, AI tool, automatic save, portfolio state, formal decision, or trade is created.

A separate `next_day_verification.sqlite3` journal lives under `VR_DATA_DIR`, falling back to the existing `~/.vibe-research` convention. Only explicit PUT initializes it. GET initializes neither journal nor source DB. Unreadable or malformed journal state fails closed with a stable error; even an unrelated corrupted old journal row blocks the current read rather than silently disappearing from history.

## Time, evidence, and atomicity

- The review date must be a confirmed session. Saving opens after that session's Shanghai 15:00 close and stops at exactly the next confirmed session's Shanghai 09:15. Unsupported calendar horizon, unknown calendar, weekends, holidays and future/unclosed dates do not permit writes.
- SQLite `BEGIN IMMEDIATE` serializes writers; optimistic revision rejects stale forms. The server rechecks the clock after obtaining the write lock and again immediately before updating the full row. Failure rolls back the whole evening.
- An unchanged condition retains its original timestamp, prior reading and baseline. A changed condition captures a new prior snapshot and baseline only while the evening is open.
- The additive fact-store reader reads the envelope and `stored_at` from the same row through a read-only connection and never initializes a missing source database.
- Both overall and metric-section metadata must match the requested date, normal status and final session. Each satisfies close ≤ fetched_at ≤ snapshot_at ≤ stored_at ≤ server capture time. Values must be finite, non-boolean, and in the correct domain (nonnegative integer count or 0–1 ratio).
- The baseline uses at most 60 adjacent confirmed-session pairs ending at the review date. Missing or ineligible observations break pairs; they are never bridged. Frequency is unavailable below 12 comparable pairs. Counts, possible pairs and coverage remain visible.
- Reconciliation waits until the target session's close and reads its currently stored final observation. This is a current-recorded-fact comparison, not an immutable historical outcome: later source corrections can change the outcome. Captured prior evidence and baseline remain fixed.
- Summary rate uses only decidable conditions; unknown observations stay in total/coverage. Expected frequency and excess use exactly the baseline-covered subset. These are descriptive research statistics, not investment success probabilities or realized return.

## Verification and remaining limits

Focused offline checks on the candidate:

- 269 Python tests across the journal/API, existing trade calendar and existing short-term fact store passed
- 5 frontend helper/static-wiring tests passed
- TypeScript and production frontend build passed; existing large-chunk advisory remains
- Synthetic tests use temporary data and deny outbound socket connections; covered exact sealing, weekends/holidays, unsupported horizon, two-writer conflicts, clock crossing during save, missing evidence, source-time inversion/future data, gap pairing, frozen baseline, corrupted payloads, alternate HTTP writes, unknown fields and caller timestamps

No local browser, full backend suite, live provider/model call, publication, deployment, user-computer operation or live market ingestion was performed. UI runtime acceptance and real-world data availability remain unverified. Recording is implemented; automatic verification remains pending qualified local evidence when the existing fact ingestion gate is not active. This slice does not activate that gate or backfill missing facts.


## Follow-on offline browser acceptance

A separate harness runs the built, actual DailyReview page with exact-origin,
strictly enumerated synthetic API responses. Journal fixtures are golden outputs
of the real journal service and are independently compared in the guarded Python
test suite. This is two complementary forms of coverage, not a claim that the
browser is connected to a real database during this harness.

Run after build with `npm run test:e2e:next-day-verification` in `frontend`.
`NEXT_DAY_VERIFICATION_EVIDENCE_DIR` controls screenshots and JSON request/result
artifacts. CI invokes it in a bounded five-minute step and uploads artifacts even
on failure. The local preparation performed syntax, pure fixture/helper tests,
real temporary-DB golden comparison and TypeScript/build checks only; the browser
was not run locally. A green browser verdict requires that explicit CI step.

Scenarios cover canonical Shanghai dates on a cold non-Shanghai locale/timezone,
late market-date arrival, explicit save/no autosave, repeated click while saving,
write failure retaining input, stale revision conflict and re-read, explicit clear,
sealed/unknown-calendar edit denial, missing evidence not counted as failure,
old-date responses arriving after a newer selection, and read-error recovery.
The form also explicitly checks that response date matches selected date before
rendering any saved editor or enabling a write.

The harness binds only a loopback static server. Unknown API paths, unexpected
query shapes, other origins, WebSockets, non-GET static requests and all writes
except a queued exact journal PUT are denied. Service workers are blocked. Test
HTML strips speculative preconnect/DNS links and the external font stylesheet;
application JavaScript chunks remain unchanged. No Python backend, user data,
provider/model endpoint, schedule, or real credentials are involved.

The integrated CI invocation additionally passes `--with-seal-quality` to smoke
the actual second card's archive-unconnected state. Its sole optional API mock is
the exact accepted `/api/market/seal-quality?trade_date=...` unavailable envelope;
no ratio is asserted or invented without evidence. Standalone journal-only
acceptance omits this flag. This cross-slice smoke complements the seal component
adapter and real archive/API tests; it does not replace them.
