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
