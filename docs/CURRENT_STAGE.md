# Current Stage — Recovery Coordinates

Last reviewed: 2026-08-28

This file is a **recovery pointer**, not Engineering Truth and not a second task database.

Always verify live GitHub before acting. Do not persist an exact current stable SHA here; recovering Agents must resolve the live stable and exact-head CI themselves.

## Product North Star

> Vibe-Research is a single-user, local-first A-share investment research and decision system. Its purpose is to reduce real buy / hold / sell decision errors around the user's holdings and candidates; final Formal Decision and real trading authority remain with the user.

## Current Stage

**PRX1 — Product Reality Sprint / TrendRadar-integrated baseline**

Expected handoff state after the TREND-RADAR1 closure governance completes:

- Issue **#228 TREND-RADAR1**: CLOSED / COMPLETED.
- Issue **#203**: engineering freeze restored; no autonomous feature expansion during the formal Product Reality observation unless the latest authority explicitly says otherwise.
- Issue **#162 Product Reality Sprint**: `READY_FOR_FORMAL_10_TRADING_DAY_OBSERVATION`.
- Formal Product Reality **Day 1 has not started automatically**. Never manufacture historical sessions or claim Day 1 without a real owner use session.
- Stable branch remains `feature/research-system-v01`; resolve the exact SHA and current CI live.

If live GitHub does not match the expected handoff above, report the conflict and follow the newest #203/#228/#162 comments rather than this file.

## What TREND-RADAR1 Established

TrendRadar remains a separate GPL-3.0 sidecar. Vibe does not vendor or import TrendRadar source in-process.

The accepted integration model is:

```text
TrendRadar full runtime
(crawl / RSS / filter / AI / translate / report / scheduler / notify / storage / MCP)
        ↓
Vibe TrendRadar Gateway + narrow read-only SQLite observation boundary
        ↓
Attention / Public-Opinion Observation Plane
        ↓
Intel / StockData / Watchlist / research workflow
```

Key delivered Vibe-native surfaces:

- pinned TrendRadar source/runtime identity and digest-qualified operator assets;
- loopback-only MCP gateway with strict allow-listed typed calls, timeout and fail-closed behavior;
- TrendRadar-owned SQLite narrow read-only adapter for exact rank timeline / first-last seen / crawl metadata that MCP does not faithfully expose;
- `/intel` Attention Radar read surface;
- StockData single-security Attention Context;
- authoritative Watchlist batch Attention Context;
- explicit provenance, GPL boundary, authority boundary and secrets boundary.

TrendRadar capabilities that remain intentionally upstream-native rather than duplicated in Vibe include its scheduler, keyword/AI filter, AI analysis, translation, reports, article reader, remote storage/sync, notification fanout and visual operator/config flow.

`UPSTREAM_NATIVE_USABLE` does not mean “missing”; it means the capability remains available through the intact TrendRadar sidecar and does not need a second Vibe implementation.

Known environment evidence that is not a current investment-workflow blocker:

- official Docker/report live-daemon qualification was not available on the qualification machine because Docker/Podman/WSL daemon was absent;
- the pinned source runtime, MCP, real hotlist/RSS, SQLite, rank history and client boundary were nevertheless qualified through isolated runtime evidence;
- use the repository qualification record for exact evidence rather than inventing a Docker PASS.

Version clarification:

- TrendRadar MCP product version and the Python MCP SDK/server handshake version are different version domains;
- do not classify those different numbers as a runtime identity mismatch.

## TrendRadar Authority Boundary

TrendRadar data is research observation, not investment authority.

TrendRadar may surface:

- attention / hotlist observations;
- first/last seen and rank history;
- RSS/news context;
- AI relevance/filter metadata;
- trend/lifecycle/viral/sentiment analysis;
- article/report context;
- source/runtime status.

It must not automatically create or mutate:

- Holding;
- Canonical Fact;
- Current/Formal Thesis;
- Formal Decision / Frozen Decision;
- Trade;
- Trade Attribution;
- BUY/SELL execution authority.

Hotness, relevance and sentiment mean “worth attention/research”, not “worth buying”.

## Active Product Truth Track — #162

The next high-value question is again Product Reality:

> Does the current TrendRadar-integrated Vibe materially improve the user's actual investment decision process enough to justify further engineering investment?

Use Issue **#162** as the observation contract.

Target:

- 10 A-share trading days;
- minimum valid sample defined by #162;
- a small private working set of real holdings plus one researched candidate;
- normal workflow only; do not manufacture trades, Frozen Decisions or Outcome events.

Per meaningful real-use session, record privately:

- task;
- elapsed time;
- major page span;
- repeated input;
- confusion;
- value event;
- bypass;
- blocker;
- UNKNOWN / NOT_EVALUATED / ERROR load;
- the then-live exact stable SHA.

TrendRadar-specific Product Reality questions should now be observed rather than guessed:

- does the Attention Radar reveal useful information the owner would otherwise miss;
- does StockData attention context improve candidate research or merely add noise;
- does Watchlist attention context reduce external hopping;
- is starting/operating the TrendRadar sidecar too cumbersome for a non-engineer;
- are upstream-native reports/AI/notification/operator flows sufficient, or does real use prove a specific Vibe-native convenience is necessary.

Ordinary friction is evidence. Do not automatically code around it during the observation window.

## Privacy Boundary

This repository is public.

Never put real holdings, quantities, account NAV, trade amounts, broker data, private Thesis text, personal notes, TrendRadar API keys, webhook URLs, SMTP/Telegram/S3 credentials or private feeds into GitHub.

Detailed real-use observations belong in private Notion / local project context. GitHub receives only anonymized aggregate findings.

## Known Nonblocking Follow-Up

- Issue **#220** remains a nonblocking follow-up for real Market Dump import/update and production-completeness beyond the accepted Full Market v0.1 local-artifact path.
- Issue **#169** remains a historical/read-only deep-audit asset; do not restart it unless new evidence makes it the highest-value action.
- Docker/report live-daemon qualification can be replayed later on a machine that actually has the required runtime; it is not a reason to manufacture another feature Slice now.
- Do not expose arbitrary TrendRadar MCP calls or real notification sends merely for UI completeness. Reopen those only if a concrete owner workflow requires them.

## Immediate Recovery Actions

1. Read root `AGENTS.md`.
2. Resolve live `feature/research-system-v01` SHA and exact-head CI.
3. Read **#203 latest comment** for current freeze / authorization state.
4. Read **#228 latest comments** to confirm TREND-RADAR1 is actually closed and no later owner override reopened it.
5. Read **#162 latest comments** for Product Reality readiness and whether Day 1 has actually begun.
6. Inspect current open PRs only to avoid duplicate work; historical Drafts are context, not active work.
7. If Product Reality is READY but Day 1 has not occurred, report `READY / NOT_STARTED`; do not fabricate a session.
8. If Product Reality has begun, continue the observation contract instead of inventing engineering work.

## Read First — GitHub

1. `AGENTS.md`
2. `docs/CURRENT_STAGE.md`
3. Issue #203 latest comment
4. Issue #228 latest comments
5. Issue #162 latest comments
6. live stable / exact-head CI
7. only source/tests relevant to an observed blocker

## Read First — Notion

Use the connected Notion workspace for durable/private product context. Search these exact page titles first:

1. `Vibe-Research｜A股投资决策系统`
2. `TrendRadar × Vibe-Research｜全能力接入调研与架构决策｜2026-08-27`
3. `Vibe-Research｜GLOBAL-ACCEL2 全面推进｜2026-08-25`
4. `Vibe-Research｜Architecture Reality Map`

Notion does not override live GitHub implementation or execution state. If durable intent and live implementation disagree, report `Intent vs Reality conflict`.

## Legacy Current-State Documents

The following files are historical context, not current authority:

- `docs/PROJECT_STATE.md`
- `docs/NEXT_TASK.md`
- `docs/CHAT_HANDOFF.md`

Do not let them override live GitHub, #203, #228, #162 or this recovery coordinate.

## Durable Engineering Invariants

- User owns formal investment authority.
- Provider/TrendRadar Observation != Canonical Fact Authority.
- Research Runtime != Canonical Fact Authority.
- TrendRadar stays outside Vibe as an independent GPL sidecar.
- Real user data and credentials stay local/private.
- Reuse existing product/authority paths before creating competing systems.
- Product Reality evidence outranks speculative feature demand.

## Deferred / Escalation Boundary

Do not autonomously cross:

- destructive migration or irreversible user-data rewrite;
- broker/order/automatic trading execution;
- new paid account/service or material recurring cost;
- credential/account-security changes;
- non-loopback TrendRadar/MCP exposure without a separate authorization/threat model;
- unresolved conflict between plausible Formal Authorities;
- irreversible real-user holdings/trades mutation without an explicit user action.

## Recovery Output

Return once at new-session / handover recovery:

```text
CURRENT ENGINEERING STATE

STABLE_BRANCH:
EXACT_STABLE_SHA:
AUTHORIZATION_STATE:
STATE_AUTHORITY:
CURRENT_STAGE:
ACTIVE_ISSUE:
ACTIVE_PR / HEAD:
LOCAL_WORKSPACE:
CI:
CURRENT_BLOCKER:
BLOCKING_DEFECTS:
PRODUCT_REALITY_BLOCKERS:
DEFERRED_SCOPE:
SOURCE_CONFLICTS:
NEXT_ACTION:
```

Then follow the newest #203 + #228 + #162 authority. If the project is frozen and Product Reality is merely READY, do not start a new engineering Slice without a new explicit owner instruction or an allowed critical/path-blocking hotfix.