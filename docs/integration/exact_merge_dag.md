# Exact Future Merge DAG (PROPOSAL ONLY — DO NOT EXECUTE)

Base:

```text
feature/research-system-v01
@1be2ecba505a8108740c311c103a2c72d3bcd444
```

This is a **recommendation for future authorized merges**.  
`PR_READY = NO`, `MERGE = NO` for this consolidation task.

## Recommended production merge order

| Step | Source PR | Source full SHA | Strategy | Why required | Dependency satisfied by | Potential conflict | Test gate |
|---|---|---|---|---|---|---|---|
| 1 | #80 (+#78) | `96d8236c2cb249e7b2b763bd68890da8d1ed6efd` | merge | DS-A1 contract + North Star docs | stable | docs/NEXT_TASK | `test_data_contracts.py` |
| 2 | #81 | `c6b5d7ff416e88289e58ad6aa7133cbf6623c75f` | merge | inventory docs | #78 | low | docs-only |
| 3 | #82 | `41918133171c19cbb729a4930e73572e70fe0493` | merge | ashare gap docs | #80 | low | docs-only |
| 4 | #97 (via S1–S3) | `657265e1eb442e86d88656c6db96bfdb6a6aff6f` | merge | Fact Lake S1A–S3 + Q1 | #80 | requirements locks | fact lake + selection suites |
| 5 | #96 (via H1/H2) | `a5c3935d6417bd44476a42975beb8dc5a2c296f8` | merge | Health H1–H3 on same head as Q1 | S2 + H1 ancestry | additive modules | health + legacy projection suites |
| 6 | #73 | `07389e4debf20bbfd61bf521d03a9aba65f7afa6` | merge | Formal Thesis runtime authority | stable | NEXT_TASK, campaign/evidence | thesis lifecycle/projection |
| 7 | #75 | `4f1d91f9553f66884b993a7d60dbff5313c9132a` | merge tests | concurrency acceptance | #73 | low | `test_formal_thesis_concurrency.py` |
| 8 | #77 (via #76) | `4b9aabf6631d87bedbcc98ccd763c02933cd1ea2` | merge tooling+tests | migration tooling for future authorized use | #73 | store migration hooks | migration suites **temp DB only** |
| 9 | #87 | `0444111a3934307edc8b5add8adba273833ba3b5` | merge | campaign re-entry pure domain | stable | low | `test_campaign_lineage.py` |
| 10 | #95 (via #88/#89/#92) | `6461ebd27adeacf141b72f7f4b4ee3c82947523e` | merge | Decision→Attribution→PA→Outcome | stable + #88 chain | performance_attribution_service | decision chain suites |
| 11 | synthetic consolidation commits | integration head | optional squash/docs | registries + integrated regression | steps 1–10 | docs only | consolidation suite |

Alternative: merge **this synthetic candidate branch** after independent review instead of replaying PR merges one-by-one (candidate already proves coexistence).

## Do NOT merge as authority / out of scope

| PR | Reason |
|---|---|
| #91 | SUPERSEDED by #95 |
| #72 as independent API | OPTION B: runtime authority is #73; pure core not separate merge authority |
| #74 | QA history evidence only (optional test cherry-pick) |
| #59 | OUT_OF_SCOPE frontend P2 pre-dating Formal Thesis / Fact Lake |
| #64 | BLOCKED market regime; DO NOT TOUCH |
| #69 | duplicate/superseded alert draft; leave alone |

## Post-merge still NOT automatic

```text
REAL_USER_DB_MIGRATION = requires separate user authorization
PR #94 body metadata drift fix = before Ready/Merge of #94 alone, or note in release notes
production canonical switch = forbidden here
```
