# Observation and private reminder workflows (P4/P7)

## Scope and source

Independent Python/React adaptation of the behavioral contracts reviewed in
[simonlin1212/vibe-astock at d5bf80d](https://github.com/simonlin1212/vibe-astock/tree/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace):
`shortline/watch.ts`, `intraday.ts`, `verification.ts`, `verify_metrics.ts`, and
`finance/schedule.ts`. The source is Apache-2.0; no upstream source code/runtime
has been copied into this implementation. Existing project licenses remain unchanged.

## Product entry

Daily Review now includes six observation slots, persisted intraday events,
source/observation timestamps, internal task results, and pending verification
reconciliation. Decision Inbox reuses the same task/reminder component without
changing campaign, thesis, trade or frozen-decision authorities. The existing
condition editor supports eight versioned market readings.

`GET /api/observation-workflows/{day}` only reads local materializations.
`GET /api/observation-workflows/preview` executes deterministic synthetic inputs
through the real software producers in a request-local in-memory database.
It never modifies the user's archive, reads their plans, or requests a provider.
`POST /{day}/tasks/{kind}/run` explicitly executes a bounded local-only task;
`POST /{day}/tasks/{kind}/acknowledge` records only that a task was read.
Neither endpoint accepts caller timestamps, recipients, secrets or provider URLs.

Missing input remains visible. Local-only premarket and announcement tasks do
not pretend that disconnected producer ports checked the market. Their internal
producer adapters are implemented and exercised offline; activation requires a
separate approved connection to the existing runtime, not another scheduler.

## Temporal/storage contracts

- Official offline exchange calendar, Asia/Shanghai; no weekday fallback
- Slots: 09:25, 09:35, 10:00, 11:30, 14:00, 15:00; end-exclusive 4-minute
  auction window and 8-minute other windows. Starting and completing a capture
  must both remain within its actual window; no retrospective replacement
- Auction uses provider open/previous close; other slots use latest/previous
  close. Provider clock must be known, same day, not future and <=60 seconds old
- Each successful `(day, slot)` is immutable. Failed/partial attempts do not
  consume a successful snapshot. Maximum three attempts, >=30 seconds apart
- SQLite `BEGIN IMMEDIATE` serializes concurrent producers across UI windows;
  no second event is emitted for an identical timestamp/state. Detection requires
  >=60 seconds of baseline within 180 seconds, >=1.5% move, 300-second per-kind
  cooldown. Lunch/auction are excluded; afternoon/source/previous-close changes
  reset comparison state. Unknown limit state cannot imply an opening/sealing
- Materializations use dedicated `observation_*` tables in the existing
  short-term facts database. They do not overwrite final daily snapshot keys
- GET directly reuses the accepted FactLake `_ControlSnapshot` stable byte/descriptor/Windows/sidecar contract, clones checkpoint bytes into memory, refuses pending journal/WAL,
  and does not create source DB/schema/WAL/SHM or migrate it
- Announcement adapter requires a complete <=50-row source page and precise
  provider timestamps. Oversized, partial, duplicate, foreign-identity or
  conflicting pages leave that symbol's cursor unchanged. Valid symbols commit
  independently; complete records and cursor advance are atomic
- Premarket must complete before 11:30. Due time is the next official session
  at 16:30; later reads keep unresolved past due conditions visible without
  moving the deadline or calling missing evidence a failed condition

## Eight-condition evolution

The original two readings retain the exact qualified-final-fact provenance and
frozen baseline contract. Old journal rows are read without rewriting them.
The response is `next-day-verification.v0.2`; old response fixtures remain
readable by the frontend. No automatic storage migration is required.

Six new readings freeze a distinct `verification-research-observation.v1`
evidence object at the actual user save. It records server observation time,
exact source receipt IDs/hashes, definitions and a digest of the receipt set.
It does **not** invent `stored_at` or claim the historical close was then known.
Their historical baseline remains null. P2/P3 synthetic archives are excluded
from real plan evidence. Target reconciliation explicitly uses the current
stored posthoc archive and may change after source correction; the frozen prior
reading never changes. No new historical samples are backfilled into old plans.

Mappings: descriptive highest source board; complete source-streak 1-to-2 cohort
promotion (not FrozenGate); previous limit-up cohort median return in percentage
points; same cohort losses **>=5%** (inclusive, adapted to the precise local
contract); largest vendor-tag stock share with complete attribution; complete
source market limit-down count. Unknown coverage remains null. The legacy
readiness card continues to describe only its two qualified-final-fact inputs.

## Verification boundary

Focused guarded Python tests cover slot boundaries, incomplete attempts,
concurrent writers, stale/unknown/future quotes, persisted cooldowns, cursor
rollback, local-only API actions, readonly file identity and immutable prior
conditions. TypeScript and production-component readback tests verify response
identity and recovery. Browser acceptance is prepared for existing GitHub CI;
no local browser is launched. These are software/synthetic checks, not a real
trading-session, provider, notification-delivery, model-quality or Day 1 claim.
All live collectors, scheduler registrations, external notifications, merge and
deployment remain disabled/outside this slice.


### Bounded restore and UI follow-up

Every materialization is validated against its SQL identity before display or
reuse; successful slot computations, source clocks and deterministic event IDs
are rechecked. Research receipt restore validates the same exact source versions,
hashes, provider IDs and capture/receipt timestamps as fresh saves, even if a
corrupted file recomputes its receipt digest. Non-finite derived returns are
rejected, not serialized. Watch frames cap at 181 within the 180-second window;
higher-than-supported quote rates are explicitly not compared. Event output
shows the most recent 500 plus total/has_more. Due reconciliation evaluates the
20 most recent eligible plans and exposes total/remaining coverage; older plans
remain directly accessible through the existing date-specific condition view.

Embedded observations wait for the parent review date; Inbox explicitly owns
its Shanghai-today default. A malformed task readback locks further task actions
until an explicit successful reread. Existing CI browser acceptance now includes
six-slot preview, source-time expansion, viewport fit and malformed-read recovery
on desktop and mobile. It is prepared, not claimed to have run locally.

### Cross-package verification

The portable `test_observation_cross_package.py` exercises P2/P3 integration:
raw provider-shaped bytes in a fresh temporary FactLake, versioned acquired-path
receipt admission, real daily/cohort/theme queries, all eight condition prior
readings, exact receipt freeze, and target-date reconciliation. The temporary
records use `fixture=False` solely to test that branch; the test is synthetic and
never claims real acquisition. The condition adapter requires exact current/
official-prior date dependencies per metric and independently removes invalid
or preclose source receipts without hiding unrelated valid metrics. All eight
priors are exercised; a missing target 1-to-2 cohort remains unknown.
