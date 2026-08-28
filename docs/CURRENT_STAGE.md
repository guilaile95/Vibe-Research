# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-28

This file is a recovery pointer, not Engineering Truth and not a second task database.
Always resolve live GitHub state before acting; do not persist an exact stable SHA here.

## Current Stage

**NATIVE-INTEL1 — Replace the legacy TrendRadar sidecar with Vibe-native Intel**

Issue [#236](https://github.com/guilaile95/Vibe-Research/issues/236) is an explicit Owner Override of the restored freeze recorded in #203. It replaces the previous assumption that TrendRadar remains a permanent runtime dependency.

Target end state:

```text
Start Vibe-Research once
        ↓
Native RSS acquisition + local SQLite history
        ↓
normalization / exact dedupe / source health / observations
        ↓
A-share company / industry / concept mapping
        ↓
Intel / StockData / Watchlist
```

The product must not require a sidecar process, MCP client, `VIBE_TRENDRADAR_MCP_URL`, or a second project checkout.

## Active Authority

- Issue #236 owns the current engineering slice and completion contract.
- Stable remains `feature/research-system-v01`; resolve its exact SHA and exact-head CI live.
- Work stops at a reviewed Draft PR / Ready-to-merge state. Do not merge or push stable without separate Owner authorization.
- Issue #162 Product Reality is paused while NATIVE-INTEL1 is implemented.
- Formal Product Reality Day 1 remains `NOT_STARTED`; engineering/browser validation must not manufacture a real-use session.

## NATIVE-INTEL1 Scope

Required:

- source registry and per-source fetch status;
- local SQLite items, observations and restart recovery;
- `published_at`, `observed_at`, `first_seen_at`, and `last_seen_at` remain distinct;
- exact dedupe and single-source failure isolation;
- honest `normal / partial / stale / unavailable` states;
- RSS sources never receive invented rank values;
- A-share code, company, industry and concept mapping, with fail-closed unknowns;
- Native Intel APIs for status, items, refresh, trending, security context and Watchlist context;
- `/intel`, StockData and Watchlist read only the Vibe-native data plane;
- AI is optional enhancement and cannot break deterministic information access;
- remove all legacy sidecar, MCP, runtime, CI, lock and operator dependencies.

Explicitly deferred:

- notifications;
- AI translation;
- S3 or remote sync;
- standalone HTML reports;
- MCP compatibility;
- a provider configuration backend;
- vector databases or queues;
- a new crawler framework;
- commercial-news full-text mirroring;
- unrelated refactors.

## Authority Boundary

Native Intel is a research observation plane, not investment authority.

It may provide public-news metadata, source health, first/last observation, deterministic trend counts, and entity context. It must not automatically create or mutate Holdings, Canonical Facts, Current/Formal Thesis, Formal/Frozen Decisions, Trades, Trade Attribution, or BUY/SELL authority.

Unknown and failed inputs remain UNKNOWN or explicit failures. Source failure must not become an empty-success response. AI failure must not remove deterministic items, history, filters, mappings, or trends.

## GPL / MIT Boundary

- The legacy GPL system is only a historical behavior reference.
- Do not copy its source, comments, file structure, identifiers, or implementation expression.
- Native Intel is designed from Vibe-owned code and permissive/public interfaces.
- Library license and upstream data rights are separate checks.
- Real user data, credentials, private feeds and model keys stay outside Git.

## Product Reality Track

Issue #162 remains the durable real-use observation contract, but does not run concurrently with this implementation slice. After #236 is merged and a new stable is explicitly accepted, the Owner may start Day 1 through an actual use session. Do not backfill or fabricate sessions from tests.

## Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve live stable SHA and exact-head CI.
3. Read Issue #236 and its latest comments.
4. Inspect the active NATIVE-INTEL1 PR and its latest review/CI.
5. Read #203 and #162 only to confirm the override and Product Reality pause.
6. Inspect the local workspace before touching files; preserve uncommitted work.
7. Continue the existing implementation instead of opening a competing branch or architecture.

## Durable Invariants

- The user owns formal investment and trade authority.
- Public-provider observation is not Canonical Fact authority.
- Real holdings, account values, credentials and private research remain local/private.
- Reuse existing Vibe capabilities before adding dependencies.
- Build the smallest correct source-to-sink replacement, keep it working, and stop at Ready-to-merge.
