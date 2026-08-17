# P0-DC1 Decision Commit Vertical — Parallel Work Order v0.1

> Status: STACKED_PARALLEL_DEVELOPMENT_AUTHORIZED
> Base: `integration/p0-hr1-hard-risk-runtime-v0.1@f56f8a69d9e95613b3d54ab63c24aa99e437d529`
> Ready/Merge: NO — remains a separate user authorization gate.
>
> This document is an execution contract for parallel development. It is not a new product authority and does not replace `docs/PRODUCT_NORTH_STAR_V01.md`.

## 1. Product question

For one exact `Security + Strategy + Campaign`, can the user move from current authoritative facts to a reviewable Formal Decision proposal, explicitly confirm it, freeze an immutable Frozen Decision, and have Decision Inbox consume the resulting Formal Decision evaluation?

Target vertical:

```text
Current Thesis
+ Critical Data
+ Hard Risk
+ Material Change
+ sell-side / action-envelope inputs
→ Decision Assurance at one literal as_of
→ Asset View + Trade View + Portfolio View
→ Next Best Action + Action Envelope
→ explicit user review / confirmation
→ Frozen Decision Snapshot
→ Decision Inbox reflects real Formal Decision evaluation
```

## 2. Frozen invariants

- Decision Unit = `Security + Strategy + Campaign`.
- All decision-authority results used by one proposal must apply to the same literal `as_of`.
- `UNKNOWN != NOT_EVALUATED != ERROR`; no greenwashing in runtime or UI.
- Asset View / Trade View / Portfolio View remain separate; never collapse to a single BUY/SELL.
- Existing `frozen_decision_service` / `frozen_decision_store` remain the immutable commit authority; do not create a competing decision store.
- Existing `decision_assurance_projection` remains coverage authority; do not reimplement RA1.
- Existing `formal_thesis_projection_core` remains Current Thesis semantic authority.
- Existing HR1 contract/runtime remain Hard Risk authority for v0.1.
- Existing EC1 (`decision_evidence_delta_projection`) is temporal-delta authority only: `NEW EVIDENCE != MATERIAL CHANGE`.
- Reuse the accepted #107 Sell Engine semantics where valid; do not merge the old branch wholesale or treat naked provenance refs as verified authority binding.
- Proposal != Frozen Decision. A proposal must never be presented as current committed advice.
- No Frozen Decision is created without an explicit user confirmation action.
- AI may be user-triggered later, but v0.1 commit correctness must not depend on automatic AI calls.
- No broker integration, no order execution, no automatic trading.

## 3. Parallel lanes

### C — Domain / deterministic authority

Branch: `feat/p0-dc1-decision-domain-v0.1`

Own:
- Material Change v0.1 deterministic authority and contract.
- Decision proposal pure composition contract.
- Reuse/absorb #107 Sell Engine core semantics only after binding inputs to named authorities.
- Action Envelope deterministic composition boundary.
- Domain tests and frozen JSON fixtures consumed by O/Z/G.

Do not own:
- SQLite, FastAPI, filesystem, network, frontend, user confirmation persistence, AI calls.

Required semantics:
- Material Change must consume named normalized evidence facts; `has_new_evidence=true` alone cannot imply MATERIAL.
- incomplete inputs stay UNKNOWN/NOT_EVALUATED/ERROR.
- Hard Risk constrains envelope but does not mechanically emit EXIT.
- `LOSS ALONE != SELL REASON`; `PROFIT ALONE != HOLD REASON`.

### O — Runtime / same-as-of / commit adapter

Branch: `feat/p0-dc1-decision-runtime-v0.1`

Own:
- same-as-of adapters for Current Thesis / Material Change / Formal Decision evaluation.
- runtime composition into RA1 and Decision Inbox.
- proposal API and explicit commit API.
- mapping a user-confirmed proposal into existing `frozen_decision_service` without bypassing its validators/hash/store.
- idempotency/conflict/fail-closed integration tests.

Do not own:
- Material Change business rules, Sell Engine rules, UI rendering rules, new decision persistence.

Required semantics:
- exact Security/Strategy/Campaign identity gates.
- exact literal `as_of` gates.
- evaluator/runtime failure never becomes EVALUATED/CLEAR by fallback.
- commit endpoint requires an explicit confirmation payload and revalidates proposal identity/version before freeze.

### Z — Product UI / review and explicit commit

Branch: `feat/p0-dc1-decision-review-ui-v0.1`

Own:
- Campaign-scoped Formal Decision review surface.
- separate Asset / Trade / Portfolio panels.
- Next Best Action + Action Envelope + Maintain/Upgrade/Downgrade/Invalidation conditions.
- visible data/authority uncertainty states.
- explicit review/confirm/freeze interaction; no automatic commit.

Develop against C frozen fixtures and O API contract; do not wait for real runtime.

Do not own:
- backend decision semantics or authority inference.

Required semantics:
- Proposal visibly labelled as proposal/uncommitted.
- UNKNOWN / NOT_EVALUATED / ERROR cannot look healthy.
- confirmed Hard Risk is prominent but never rendered as an automatic EXIT command.
- Frozen Decision state is shown only after backend commit succeeds and the returned committed record is re-read.

### G — Integration gate / adversarial acceptance

Immediate branch: `fix/p0-hr1-top-risk-ci-v0.1`

First mission:
- close #132's only current CI blocker: unrelated `top-risk` Playwright 404 without masking genuine `/api/*` failures.
- preserve existing top-risk semantics; test-harness hardening only unless a real product defect is proven.

Then branch: `test/p0-dc1-decision-commit-e2e-v0.1`

Own:
- vertical acceptance matrix and real FastAPI + isolated DB + built frontend + Chromium E2E.
- independent identity/as_of/provenance/adversarial review on integrated head.

Must prove:
1. proposal cannot freeze without explicit confirmation;
2. identity/as_of mismatch fails closed;
3. UNKNOWN/NOT_EVALUATED/ERROR never becomes clean/committable;
4. Asset/Trade/Portfolio remain separate;
5. committed Frozen Decision round-trips through existing hash/store authority;
6. Decision Inbox receives real Formal Decision evaluation after commit;
7. no broker/order path exists;
8. no real-user DB is touched in tests.

## 4. Fan-in topology

```text
#132 HR1 exact head
  ↓
DC1 shared work-order/contract seed
  ├─ C domain
  ├─ O runtime
  ├─ Z UI
  └─ G E2E/gate
       ↓
integration/p0-dc1-decision-commit-v0.1
       ↓
real vertical E2E + exact-head CI + independent review
       ↓
user Ready authorization
       ↓
user Merge authorization
```

No rebase, no force push. Ordinary merge commits for fan-in.

## 5. Integration Hygiene runs in parallel

The DC1 stack is speculative and must not block cleanup of the existing chain:

```text
stable fdeb7da
→ #128 Current Thesis activation d4ad875
→ HR1 shared contract bc403efe
→ #132 HR1 runtime f56f8a69
```

Facts at work-order creation:
- #128 exact head has a successful push CI run; Ready/Merge still not authorized.
- #132 exact head has HR1-specific backend/frontend/vertical jobs passing, but overall CI fails in the pre-existing top-risk Playwright job on a 404 console error.

If stable advances, merge the new stable forward into the relevant integration branches; do not rebase reviewed/pushed history.

## 6. Stop boundary

This work order authorizes parallel development only.

It does NOT authorize:
- Ready / Merge of #128, HR1, #132, or DC1;
- direct stable push;
- real-user database writes or migration;
- automatic AI analysis/commit;
- broker connection or order execution;
- unrelated security/home/mobile redesign work.
