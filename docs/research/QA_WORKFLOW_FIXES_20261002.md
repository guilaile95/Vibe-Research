# Research workflow QA fixes — 2026-10-02

Three independently reproduced P2 frontend defects are fixed: truncated evidence coverage, a stock query that disagreed with its URL, and silent loss of unsaved research forms. These are separate from the earlier K-line source, financial zero and holdings cancellation defects.

## Version and scope

- Original stable QA snapshot: `aab09365f5bb18699268aafe7ff333e84c71c87d`.
- Reproduced frontend defects: PR356 snapshot `15804a72a2d6da69e8f40048003ad58f8a58909b`.
- Implementation parent: `0bc2f48402e2c97de77b4d3875604069119efed4`, a normal cherry-pick of backend fix `b1abd0b0509e079ae0a530df670068467b244e84` onto PR356. Its tree is `77f8c84733767b2a8f4d99e121c82f5287d65190`, matching the separately supplied PR358 tree.
- This patch changes frontend pages, two small frontend helpers, regression tests and this report. It does not modify backend code, dependencies or the user's existing working tree. No merge or release is implied.

## Reproductions and resulting behavior

### DATA-01 — coverage silently omitted evidence after row 200

Create 201 synthetic evidence records for one security in an isolated SQLite store. The first page contains 200 low-confidence news inferences; row 201 is a high-confidence financial fact with a newer source date. Open Candidate Research and refresh at desktop and 390-pixel width. Previously the page reported total 201 while claiming zero financial records/high-confidence facts and showing the older date.

CandidateWorkspace now loads all evidence pages before publishing coverage. It validates totals, offsets, expected counts and duplicate IDs, then rereads the first page for observable head changes on multi-page loads. Missing pages, failures and detected concurrent changes show an error rather than partial coverage. Switching security cancels publication and further page reads.

This remains an offset-paginated API, not a transactional snapshot: the head check cannot prove that every possible concurrent mutation was absent. An observed inconsistency requires an explicit refresh; there is no automatic retry loop.

### RACE-01 — queried security differed from reload/Back context

Open `/stock-data?code=000001`, query `000002`, refresh, or enter Candidate Research for B and go Back. Previously the displayed security changed to B while the URL remained A, so reload/Back restored A.

Different-security submission now pushes the updated code into the URL; the URL change starts the query. Back/Forward and supported international code deep links use the same entry. Same-security retry queries again without adding history. Other query parameters and the hash are preserved; stale responses cannot overwrite a later security or the empty entry reached through Back.

### RESEARCH-01 — unsaved evidence/thesis inputs disappeared silently

Enter new Evidence or Thesis text, then follow an in-app link, go Back or refresh. Previously unsaved text disappeared without warning. Both pages now warn on in-app navigation and native unload, with explicit stay/discard choices for in-app navigation.

Save failures preserve the dirty form. During an active save, edits, repeated submits and in-app discard are blocked. A successful save proceeds to its destination; a partially created Campaign thesis proceeds to the existing record without repeating creation. Changing the same page's query context after confirmed discard remounts the form and its baseline. Thesis array text typed before pressing Enter is included in dirty tracking and Save.

The native browser controls reload/close warnings. Closing or reloading cannot guarantee cancellation of an already submitted server request; this patch does not promise recoverable drafts after an accepted unload.

## Validation of the final source

- TypeScript project build and Vite production build passed.
- Relevant Node tests: 30/30 passed, including six new evidence pagination tests for 201/401 records, empty/exact page sizes, late failures, observed changes and cancellation.
- Stock navigation browser regression: seven groups plus eight A/B/Back/Forward cycles passed, including delayed responses and AAPL/00700/005930.KS reload.
- Unsaved form browser regression: 17/17 passed, including native reload dismissal, failed/pending saves, same-path context changes, Campaign hydration and partial creation.
- Original real Uvicorn + isolated SQLite evidence/thesis browser flow: all ten stages passed, including edit/revision diff, immutable evidence history, soft deletion, archive and duplicate archive 409.
- Data UI regression: 15 states passed; additional semantic regression: 11 states and 20 assertions passed. The 201-record SQLite fixture now shows one financial fact, one high-confidence fact and source date 2026-10-01 on desktop/narrow layouts.
- Independent Astra review initially found same-path form reuse after discard. The fix was reviewed and four focused browser checks passed; the final six production-file SHA256 values were bound to the review ledger. No remaining blocker was found within this bounded review.

Repeatable frontend checks after installing the project's existing dependencies and building:

```sh
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
node --experimental-strip-types --test tests/qa-evidence-coverage.test.ts tests/candidateCampaign.test.ts tests/candidateEntryContext.test.ts tests/candidateResearchNote.test.ts
node tests/e2e/qa-stock-navigation.browser.mjs
node tests/e2e/unsaved-create-forms.browser.mjs
```

Browser tests use Playwright. If a browser executable is supplied locally, the stock script accepts `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; the form script accepts `PLAYWRIGHT_CHROMIUM_PATH` and otherwise checks the existing Windows Playwright cache. Each script owns and closes its temporary browser/server.

Frontend fixtures are synthetic and external network is blocked. These checks verify interaction, rendering and persistence boundaries; they do not validate live provider prices, paid model quality, real portfolios or long-term production stability. Screenshots, execution logs and the bounded endurance ledger are kept with the separate QA evidence delivery.
