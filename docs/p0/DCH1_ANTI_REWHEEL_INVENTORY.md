# P0-DCH1 Anti-Rewheel Inventory

Base: `6708f9b96fdc8c999ea559409adb254020a195fc`

## Authority ownership

| Area | Existing authority | DCH1 decision |
| --- | --- | --- |
| Decision Proposal preview / fingerprint / stale gate | `decision_commit_runtime.py` `_fingerprint` / `commit_decision_proposal` | Reuse as the only Proposal authority. Challenge is not a proposal field and is not hashed into `decision_proposal.fingerprint.v0.1`. |
| Decision Proposal identity / NBA / envelope | `decision_proposal_projection.py` | Read-only reuse via existing preview path. Challenge content never feeds NBA, envelope, HR, Material Change, or CCD. |
| Frozen Decision write + `source_refs` | `frozen_decision_service.py` / `frozen_decision_store.py` | Reuse existing optional `source_refs`. Server appends `decision_challenge:<id>` in `_freeze_payload`. No schema-key change. |
| Campaign / Current Thesis identity | `campaign_service` + `formal_thesis_projection` via DC1 runtime | Re-read server-side. Caller cannot submit security/strategy/thesis. |
| Decision Proposal Review UI | `frontend/src/pages/DecisionProposalReview.tsx` | Add optional Challenge panel. Freeze remains possible without a packet. |
| Old Draft PR #114 | `decision_challenge_projection.py` at `6d213626` | Vocabulary + coverage reducer only. Not merged. Not production authority. |

## #114 absorption (safe subset)

Absorbed:

- Four dimensions: `STRONGEST_SUPPORTING_EVIDENCE`, `STRONGEST_OPPOSING_EVIDENCE`, `PRE_MORTEM`, `INVALIDATION_FACTS`
- Coverage evaluations: `EVALUATED` / `UNKNOWN` / `NOT_EVALUATED` / `ERROR`
- Packet states: `COMPLETE` / `INCOMPLETE`
- Two-pass structural states: `VALID` / `INCOMPLETE`
- `UNKNOWN` counts as coverage and is never positive evidence
- `TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED=NO`
- `CHALLENGE_COVERAGE != DECISION_CORRECTNESS != DECISION_APPROVAL`

Rejected from #114:

- Caller-submitted dimension `evaluation`
- Caller-submitted `authority_refs` / `artifact_refs`
- Caller-submitted `challenge_requirement` as a freeze gate
- Upstream-binding-not-verified as an acceptable production posture
- Mandatory challenge / blocking Freeze
- Any decision-quality grade

## Rejected rewheels

- No merge of PR #114.
- No second Frozen Decision store or schema migration.
- No second Proposal fingerprint / authority path.
- No CF1 price / Formal Outcome / `process_quality` integration.
- No AI challenge generation or scoring.
- No caller-declared evaluation or formal authority.

## DCH1 ownership boundary

1. Trusted producer is the server-finalized Challenge Packet.
2. Public finalize input is user review content/status only.
3. Evaluation and `decision_challenge:<id>:<dimension>` refs are server-derived.
4. Challenge is optional and non-blocking at Freeze.
5. `DECISION_QUALITY = NOT_EVALUATED`.
