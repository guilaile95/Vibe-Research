# Public-code integration and acceptance · 2026-10-04

Dated engineering snapshot. Stable, Draft code, preserved desktop edits and running
services are separate surfaces. Nothing here authorizes a merge or deployment.

## Reproducible public baseline

The tested runtime tree is [#374](https://github.com/guilaile95/Vibe-Research/pull/374)
head `f1acf24e1cd6e3d4484b1c99c57f6edb5c9ed0cb`, tree
`47c872b58bd1c155f5e80aca2dbe60edd91e582c`. It includes #356/#358/#363–#369,
and the non-stable integration branch combines #359 and #360 before #370–#374.
Remote ancestry checks confirmed #359, #360, #369 and #373 are ancestors of #374.
The old #363 head's Windows failure remains historical; #364 fixed the connection
lifecycle, with later exact-head Windows verification.

Public documentation integration adds:

- #361 `a3458588126dbeea3d23c12dd5cebb54b413f1e3`: 12 files, including the 10-line
  AGENTS delivery-scope addition and installation/document-navigation guides
- #362 `5c291f889a606055f8037bc26150d3f0dd2ff647`: two-line portable validation-command
  adjustment removing a private absolute path

Only `backend/README.md` conflicted. Resolution keeps the newer guide/navigation
and the existing `/api/ai/connection-test` entry and cost/quality limitations.
Runtime source and tests are byte-identical to #374; docs-only integration uses
link/path, conflict-marker, whitespace and tree comparisons, not another full suite.
The dated October 2 snapshot remains historical and is superseded here where noted.

## Acceptance matrix

| Lane | Established | Still outside the evidence |
| --- | --- | --- |
| Implementation | #364 SQLite closure; #365 calendar recovery; #366 incomplete-reflection saving guard; #367–#369 upload/list/history/signal request ownership; #370 search invalidation; #373 bounded SHA-pinned page reader; #374 numeric-zero UI preservation | No stable merge or runtime switch; desktop-only modifications not yet combined |
| Functional QA | Each repair has focused regressions and exact-head CI; #373 11/11 CI success, 390/1440px page-reader keyboard/browser acceptance; #374 11/11 CI success including numeric-zero browser fixture | Original full QA recorded 37 routes, 15 failures in 13 families, not an all-product pass; complete final findings artifact still required to close every original item |
| AI quality | #371 verifies selected-report metadata/page/title transport, missing-page display and stale evidence rejection offline; conflict fixtures explicitly unevaluated | Historical real run remains 17 cases / 18 requests: 9 pass, 7 fail, 1 pending; no new live model evaluation. Full original report and safe provider configuration/budget are required for targeted retesting |
| Frontend design | #372 implements a bounded ResearchBrief reading-order improvement, keyboard and 390/1440px validation; representative screenshots use synthetic fixtures | The historical 16-view prototype is a design deliverable, not proof all views were implemented or retested |
| Documentation | #361/#362 public guide/redaction integrated with current recovery links; changed doc paths checked | Public AGENTS addition has not been compared byte-for-byte with the preserved desktop AGENTS edit; Notion reconciliation is a separate artifact |
| Research | #373 demonstrates explicit retrieval of a late page correction beyond a 320-character search snippet; #374 documents actual financial adapter fields and zero display repair | Retrieval is not automatic truth verification. No verified unit/scale/scope/revision payload contract; no guessed financial rules or PIT changes |

#374 exact-head CI: all 11 jobs successful, including Windows offline backend,
frontend build/tests and the numeric-zero browser fixture (checked 2026-10-04 06:19 UTC).
See [CI run](https://github.com/guilaile95/Vibe-Research/actions/runs/37180940595).

## Integration dependencies and minimum remaining inputs

1. Keep all current changes on non-stable branches. Review/integration must retain
   both #359 and #360; selecting only the linear #363–#374 stack without the public
   integration merge would lose prior accepted fixes.
2. Desktop reconciliation needs an authorized export of the preserved tracked diff
   and a file inventory/content for the 23 untracked files, with secrets/user data
   excluded or safely handled. The earlier record counts 16 tracked modifications;
   the exact content is not available in this cloud workspace. Never overwrite it
   with this public baseline. The AGENTS ten-line count alone does not prove equality.
3. Original final QA findings/coverage and `REAL_MODEL_REPORT.md` are needed to map
   all historical failures. Recorded summaries establish totals and a few concrete
   failures, not an invented complete pass/fail list. Missing artifacts do not erase
   completed independent code work.
4. Real-market freshness/coverage, safe live-model retests, user workflow value and
   any eventual service switch remain separate acceptance with the required inputs
   and explicit scope. Synthetic CI cannot stand in for those observations.

No merge, deployment, desktop write, live provider/model request or financial action
was performed by this cloud integration. See [page-reading contract](../REPORT_PAGE_READ.md)
and [financial compatibility evidence](../FINANCIAL_OPERAND_BOUNDARIES.md).
