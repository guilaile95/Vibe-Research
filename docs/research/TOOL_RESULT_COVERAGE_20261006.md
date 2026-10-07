# Investor Q&A tool coverage: bounded disclosure

## Verified gap and scope

On the `f4922dd` baseline, `astock.investor_qa` returns a bounded source window
(default requested page size 30). `ai_tools._investor_qa` then keeps 12 rows,
200 Unicode characters per question and 400 per answer. The adapter also projects
fields: company and answerer are not forwarded. Only after this projection does
`chat._serialize_tool_result` apply its separate 6,000-character JSON budget.
That serializer already disclosed its own compaction; it could not detect text
or rows discarded upstream. A response fitting its budget therefore incorrectly
looked like an unrestricted successful tool result.

Synthetic execution against the actual baseline adapter and serializer:

| Fixture | Source text | Adapter text | Model text | Old outcome |
| --- | ---: | ---: | ---: | --- |
| One question character + 400 answer characters + four-character qualification | 405 | 401 | 401 | success, context truncated=false |
| 30 rows, each 250 question and 500 answer characters | 22,500 | 7,200 (12 rows) | 3,656 (8 rows) | success, context truncated=true |

The qualification fixture fails the new regression on the baseline because
`success != partial`. These strings are synthetic, not financial assertions.
The model-text count includes ellipses introduced by context compaction.

## Contract change

`query_investor_qa` now returns an object rather than a bare array:

- `items`: the same bounded question/answer excerpts, with per-field truncation flags
- `status`: partial when rows or text were omitted, empty for no returned rows,
  otherwise success (success does not establish historical completeness)
- `adapter_coverage`: input/output/omitted row counts and omitted Unicode character
  counts for questions and answers **in selected rows only**
- `note`: excerpts can omit qualifications; source-window counts do not establish
  complete historical coverage; a missing answer remains null/unknown

Coverage scope is `adapter_input_before_context_compaction`. Output row counts
describe the adapter stage, not final model delivery after additional compaction.
Text counts do not include dropped rows or projected-out fields. No total upstream
history size is inferred. Counts and flags are metadata, not evidence of observations.

Chat prioritizes adapter coverage when compacting. Its existing envelope `truncated`
still describes **context** compaction only. Thus `partial` + `truncated=false` is
intentional for adapter-only omission. Existing streaming events carry this partial
status to the client. MCP receives the same adapter object, so consumers expecting
the previous bare list must read `items`. The HTTP `/api/investor-qa` shape is unchanged.
Debate's normal dossier does not currently request this tool; shared serializer and
empty-detection regressions are still checked.

This change discloses omissions; it does not recover them. Repeating the same tool
call is not a readback mechanism. A generic post-adapter cache cannot recover discarded
source text. Other projected tools (reports/news/announcements, list caps, GPU history
summaries) are separate bounded follow-on candidates, not covered by this fix.

## Validation (2026-10-06)

- 287 focused offline tests pass: new coverage tests plus existing Chat grounding,
  SSE and transport, MCP encoding, AI K-line, agents/Debate, signals, Tencent K-line,
  and fund-flow contracts
- 12 new cases cover qualification loss, exact Unicode boundaries, row counts,
  empty/null payloads, missing answers, two-stage compaction, MCP and streaming Chat
- `git diff --check` passes
- Baseline qualification regression: failed as expected on the old adapter
- No browser, real provider/model evaluation, full backend suite, frontend build,
  remote CI, merge or deployment was performed for this change

The change adds no framework, persistence, tool rounds or data-source calls.
