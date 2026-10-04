# Explicit indexed-page reading

`POST /api/myreports/page-read` reads existing PDF page text only. It does not
index, OCR, invoke a model, alter files, or automatically add text to AI context.
The My Reports viewer is available after selecting reports and requires an
explicit Read action. Source images, tables, extraction errors and unrequested
pages remain outside its coverage. `full_report_read` is always false.

## Request

`report_id`, `selected_report_ids`, `expected_file_sha256`, `page_from`, `page_to`.
The expected lowercase SHA256 comes from the report catalog; catalog, index and
actual source must agree. Actual source is hashed again after text retrieval;
concurrent change discards all text. Selection is a workflow scope, **not an
access-control list**. Existing local API access controls and catalog remain the
trust boundary. This is not a multi-user authorization feature.

Page endpoints must be strict positive integers <= 1,000,000, ordered and span
at most 200 pages. Invalid shape, negatives, floats, booleans, huge integers,
reversed/over-wide ranges and invalid budgets receive HTTP 422 before expansion.
Valid requests receive one classified item per requested page, including pages
beyond the document's actual page count. No page count is invented for TXT/DOCX.

Defaults: at most 8 returned pages, 12,000 total Unicode code points, 6,000 per
page. API ceilings: 20 returned pages, 20,000 total/per-page characters. A large
first page has no exemption. SQL substring bounds each extracted text response.
`indexed_chars`, `returned_chars`, `truncated` disclose partial page text.

## Coverage partition

- `readable`: nonempty useful indexed text returned; may be explicitly truncated
- `omitted`: indexed page exists but returned-page/total-character budget exhausted
- `invalid`: unselected/missing report, or page beyond known document bounds
- `unreadable`: no index, physical page numbering unavailable, no extracted page
  text, or known empty/placeholder text; blank pages do not prove OCR is needed
- `error`: mismatched/changed source SHA, unavailable source, extraction/index
  failure, or invalid source/index metadata; no source text returned

Known placeholder filtering is a narrow sentinel check, not semantic validation.
`complete_requested_text` means all requested indexed page text was returned
without truncation. It does not mean the PDF was fully read or claims verified.
The five coverage arrays partition `requested`; errors discard any earlier text.

## Offline acceptance

A synthetic PDF places a correction after the search snippet's 320-character
window. Explicit page reading retrieves it. This demonstrates access to late
text, not automatic discovery, conflict resolution or model truthfulness.
Backend tests cover partition, Unicode budget, large first page, empty/placeholder
pages, invalid ranges, missing/corrupt indexes, unpaginated files, source mutation
and read-only preservation. UI tests cover stale requests, source/version/range
changes, retries and explicit invocation; browser fixtures check keyboard and
390/1440px layouts. All fixture data is synthetic.

## Explicit AI opt-in

After reading pages, the separate “用这些指定页问 AI” action opens a scoped chat.
Opening the reader/chat does not invoke a model. Sending a question uses the
existing configured API or Codex provider and may consume that provider's quota.
Ordinary selected-report search chat is unchanged.

`/api/chat` accepts optional `report_page_context` containing only `report_id`,
`expected_file_sha256`, `page_from`, `page_to`. Exactly that one report must be in
`report_ids`. Browser page text and extra selection fields are rejected; explicit
mode ignores browser `context`. Before each provider call the server reads the
existing index again and validates catalog/index/source SHA, including the
post-read source check. Stale/error/zero-readable inputs never invoke the provider.
Reindexing a changed file does not make an old expected SHA valid.

Fixed page-text budgets are 8 pages, 12,000 Unicode code points total and 6,000 per
page. The assembled explicit prompt (coverage, serialized page text, conversation
content and the fixed API grounding instruction) is capped at 24,000 code points;
oversized input fails instead of silently clipping metadata/history. Provider
protocol envelopes and the Codex runtime's fixed instructions are outside this
application-content budget. API mode uses the existing no-tools transport; Codex
retains its existing no-tools runtime boundary. Embedded source instructions are
untrusted quoted data, not commands. This is a retrieval guard, not proof of model
truthfulness or attention to every supplied character.

Completed answers persist the server-supplied scope, five-way page partition,
per-page truncation/counts and historical source SHA with their citations. They do
not persist a separate copy of input page text; a saved model answer may itself
quote supplied text. Conversation identity includes report, SHA and range;
changing selection or closing/stopping the stream aborts the previous request.
A restored answer describes its historical context; a new question always
revalidates the source. Cancelled/error/partial answers retain existing incomplete
turn rules. Page context is not silently added to ordinary searches or other reports.

Offline acceptance stubs both API and Codex, exercises actual PDF late-correction
retrieval, stale/reindexed sources, strict budgets and no-tools transport, and
checks persisted UI metadata at 390/1440px. Historical real-model evaluation totals
remain unchanged; no paid/live model call is part of this implementation test.
