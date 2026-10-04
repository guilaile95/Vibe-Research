# Public stack dependencies and rollback · 2026-10-04

This is a dated, reproducible review map, not merge/deployment authorization.
Remote refs and ancestry were inspected on October 4. Future integration must
re-resolve them rather than treating a branch name as immutable.

## Checkpoints

| Checkpoint | Exact public commit | Dependency |
| --- | --- | --- |
| Stable `feature/research-system-v01` | `aab09365f5bb18699268aafe7ff333e84c71c87d` | Stable source boundary; running-service version remains separate |
| Public runtime integration | `0a9361bdbf414e2f4f6ae8f03e2091219ab9c678` | Three parents: #369, #359 and #360 |
| Last financial-display slice #374 | `f1acf24e1cd6e3d4484b1c99c57f6edb5c9ed0cb` | #370–#374 descend from the combined runtime integration |
| Public code/docs integration | `29a49363aa8fe8291f5dd4f2c80061c9b053b949` | Three parents: #374, docs #361, portable-path fix #362 |
| Attribution explanation #375 | `c0f937f43691e8660d02dc891a9de952b6671d18` | Descends from public code/docs integration |
| Deterministic Inbox readiness #376 | `3a5cd26c5b15be61e9af2d41fd98515c0d4584c8` | Test-only, on #375 |
| Selected-page AI #377 | `263ea152bbf917a19950ba5ae25d58d5e1e77b86` | Two ordinary commits on #376; source tree `8b7c6c0287a6d37e40638d4550740a068b1bdb7c` |

The underlying linear repair chain includes #356/#358/#363–#369. In particular,
#364 closes the Windows SQLite backup failure observed at the original #363 head.
The two integration checkpoints retain otherwise separate public #359/#360 and
#361/#362 work. Do not cherry-pick only the linear repairs and claim equivalent
coverage. The standalone-app Draft #357 and other unrelated historical Drafts are
not part of this delivery plan.

The chart/evidence linkage change is stacked directly over #377; its own PR
records the exact candidate SHA, tree and CI receipt. It changes presentation,
bounded existing read requests and tests/docs, not storage schema or data format.

## Verification and integration gates

1. Review the candidate's complete ancestry and diff against the accepted target.
   Keep both public integration merge parents. Compare the final tree, not just
   the number of commits or green checks on ancestors.
2. Reconcile the preserved desktop-only changes separately when available. Their
   exact bytes are absent from this public baseline. Never replace or discard
   them using this branch. The old count of 16 tracked/23 untracked items and ten
   AGENTS lines is an inventory clue, not proof of content equality.
3. Run focused shared-path/integration acceptance on the actual combined tree,
   followed by that exact head's required CI. An ancestor's success does not
   establish a new combined build. #377 has its own [11/11 CI receipt](https://github.com/guilaile95/Vibe-Research/pull/377#issuecomment-5980080731).
4. Original full QA findings, the original real-model report, desktop prototype
   and private change manifest remain separate inputs. Synthetic retrieval/UI
   tests do not change the recorded real-model result: 9 pass, 7 fail, 1 pending.
5. Stable integration and any running-service change require the current Owner
   scope. This document performs neither and does not activate Product Reality.

## Reversible review / rollback plan

- Before integration, the accepted stable ref and services are unchanged. To
  evaluate an earlier checkpoint, create a separate worktree/branch at its exact
  commit; preserve the current worktree and private data. No reset, force push,
  branch removal or deletion is needed.
- The chart change can be withdrawn from a proposed integration without any data
  migration: retain #377 as the candidate source checkpoint. Do not roll back
  unrelated earlier reliability fixes merely to hide chart markers.
- If an authorized merge later occurs, record its actual pre-merge stable SHA,
  resulting merge SHA, source tree and verification before a service switch. A
  rollback after publication uses a reviewed ordinary revert on a new branch,
  choosing merge parent deliberately and testing the reverted tree. Do not
  rewrite shared history or guess the correct mainline for integration merges.
- A code rollback is not a private-data restore. If a future service switch has
  written data, preserve the data and use the separately authorized, verified
  backup/restore process. This chart slice performs no business writes.

Related: [acceptance matrix and unavailable inputs](PUBLIC_INTEGRATION_20261004.md),
[chart contract](../KLINE_RESEARCH_LINKAGE.md), [page AI contract](../REPORT_PAGE_READ.md).
