# Bounded tool-projection coverage disclosure

## Verified gaps

On baseline `f4922dd`, source readers feed adapters in `backend/ai_tools.py`,
which discard rows, fields or text before `chat._serialize_tool_result` applies
its separate 6,000-character JSON budget. The serializer already discloses its
own compaction, but cannot detect material discarded upstream.

Actual baseline adapter/serializer execution with synthetic strings:

| Fixture | Source text | Adapter text | Model text | Old outcome |
| --- | ---: | ---: | ---: | --- |
| Q&A: one question character + 400 answer characters + four-character qualification | 405 | 401 | 401 | success, context truncated=false |
| Q&A: 30 rows, each 250 question and 500 answer characters | 22,500 | 7,200 (12 rows) | 3,656 (8 rows) | success, context truncated=true |

The model-text count includes ellipses introduced by context compaction. The
qualification regression fails on the old adapter because `success != partial`.
These strings are synthetic, not financial assertions.

Three additional below-budget fixtures reproduce the same missing disclosure:

- `query_reports`: an actual source `infoCode` field is projected out; only
  title/date/organization/rating remain
- `query_news`: source `新闻内容` is projected out; only title/time/source remain
- `query_industry_reports`: `infoCode` is projected out; only
  title/date/organization/industry remain

All three baseline regression cases fail with `success, truncated=false` instead
of `partial, truncated=false`. The fix does not forward discarded content.

## Final compatibility-preserving contract

All four tool results **remain arrays**, including `[]` for empty results.
Original selected fields, ordering, row limits, and Q&A text caps remain intact.
The Q&A missing-answer display placeholder `（未回复）` is preserved. It is not
additional corroboration of a source's completeness.

Coverage is attached to the **first real row only**; no artificial metadata row
is inserted and no empty result becomes evidence. New fields on that row:

- `status`: partial when the adapter omitted rows, selected-row text, or (for
  report/news tools) fields; otherwise success
- `adapter_coverage`: input/output/omitted row counts and either omitted Unicode
  character counts or omitted field counts **in selected rows only**
- `note`: source-window and excerpt/metadata-only limitations

Each Q&A row also has `question_truncated` and `answer_truncated` flags. Coverage
scope is `adapter_input_before_context_compaction`. These are metadata, not observations.
Output counts describe the adapter stage, not final model delivery after further
context compaction. Character/field counts exclude dropped rows. Q&A's existing
company/answerer field projection is unchanged and is not included in its text counts.

Chat prioritizes adapter coverage when compacting. Its envelope `truncated` still
means **context** compaction only. Therefore partial with truncated=false is
intentional for adapter-only omissions. Existing recursive limitation detection
propagates the first-row partial status to Chat events and Debate sections.

The initial local commit `c867d24` used an object envelope for Q&A. Follow-on
compatibility validation removed that unneeded shape change before publication;
use the final array contract described here, not the intermediate object contract.
Additive metadata may still affect external consumers that reject unknown fields;
external MCP consumers cannot be enumerated, and their compatibility is not proven.

## Consumer tracing and executable checks

- Chat sync and streaming paths execute the registered handler and serialize arbitrary
  JSON; synthetic executions verify actual projected results and partial trace/events
- MCP `tools/call` JSON-encodes `chat._exec_tool`; actual dispatch tests verify arrays
  and coverage with no added pseudo-row
- Debate's normal dossier includes reports and news; actual `_fetch_section` tests
  verify partial sections instead of an unrestricted success. Q&A and industry reports
  are not in its normal dossier, though the generic path accepts them
- HTTP `/api/investor-qa`, `/api/reports` and `/api/news` call `astock` directly;
  executable reader checks preserve their source fields and response shapes
- Frontend Chat consumes result status events, not the internal raw tool payload;
  no in-repository typed Q&A array consumer was found beyond these generic dispatchers
- Legacy Q&A field readers are exercised by projecting the original three keys;
  array length/order, text caps and placeholder values match the baseline contract

Report readers still request at most one page. News still requests 15 rows and
its source reader already caps the raw frame before the tool adapter; this fix
cannot measure rows lost at that earlier boundary. Source window size does not
establish complete historical coverage. No extra source/model call is added.

## Validation and limits (2026-10-06)

323 focused backend tests and 4 frontend status tests pass. These include 30
backend coverage/compatibility cases. Tests cover exact
Unicode limits, metadata-only emptiness, field/row omission counts, preservation
of source inputs, two-stage compaction, unchanged source-call bounds, MCP, sync and
streaming Chat, HTTP readers, and Debate. Baseline Q&A and three projection cases
fail as expected on the old implementations. Syntax and whitespace checks pass.

These are functional regressions, not an independent code review or a substitute
for CodeRabbit review. No browser, real provider/model evaluation, full backend
suite, frontend build, remote CI, merge or deployment was performed for this change.

This work discloses omissions rather than recovering them. Repeating the same tool
is not a readback mechanism, and a post-adapter cache cannot restore discarded text.
Announcements and other list caps, GPU summaries, and source-reader truncation remain
separate candidates requiring concrete reproduction before further changes.
