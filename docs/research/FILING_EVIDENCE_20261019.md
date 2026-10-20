# Local filing evidence and section comparison

## Source contract

Native Intel's persisted items contain title, summary, source registry identity,
URL and observation metadata, not registered original filing bodies. Its deep-read
path can fetch transient text; this feature does not call it. Existing evidence
claims also are not original document text. A missing document is shown as
unavailable, never reconstructed from a claim or model output.

The existing stock evidence detail page (financial filing or announcement type)
now offers explicit user plain-text registration. It captures the evidence edit
token and immutable evidence snapshot, issuer, user-declared source identity,
form, revision, title, optional source date and URL, exact text and SHA-256.
Dates may be unknown. All registrations permanently carry
`USER_SUPPLIED_UNVERIFIED` and `strict_asof_eligible=false`, regardless of URL or
form. This is local research input, not an official filing provider.

Corrections append a new document version referencing the original; original
bytes/text and hashes remain readable. Same identity/revision cannot be replaced.
No evidence claims, classifications, thesis revisions, event-review judgments or
formal decisions are mutated. Registration rechecks the live evidence token in
the existing ledger transaction; deleted or wrong-kind evidence fails closed.

## Deterministic structure and comparison

Plain-text Item headings support 10-K, 10-Q and 8-K (and their distinct /A forms).
10-Q keys include Part I/II; 10-K Items are global. Page-number TOC entries are
excluded. Duplicate headings, unqualified quarterly Items and ambiguous TOCs
fall back to full-document-only with a visible warning. Part boundaries terminate
quarterly sections. Announcements expose the full text without invented sections.
Offsets preserve original whitespace, numeric formatting and table text.

Comparison requires two distinct saved documents, the same exact issuer/form,
and a common section key. /A and non-/A are deliberately not interchangeable.
Line-level additions/deletions are displayed separately from interpretation;
no model interpretation is generated. Deleted source evidence is not revived.

Input is bounded at 200000 characters (at most 800000 UTF-8 bytes for valid Unicode),
100 registrations per evidence, and 100 context cards with an explicit additional
records notice. Current evidence versions are prioritized. Diffing rejects more
than 2000 lines or a million line pairs rather than silently truncating. Original
text remains available when comparison exceeds the bound.

## Safety and limitations

Text and source assertions render as escaped React text; no HTML/script execution,
URL fetching, model calls, SEC identity setup, credentials or dependency additions.
Links accept only HTTP(S) without embedded credentials. A source jump opens the
user's declared reference and does not establish provenance. Attachments are
explicitly NOT_REGISTERED; no attachments or structured facts are invented.
The implementation uses only Python stdlib concepts; no third-party crawler or
edgartools dependency/code is incorporated.

This is a bounded conservative plain-text parser, not a PDF/HTML filing parser,
a numeric fact extractor, a source verifier, or a claim that live filing data
has been tested. A complete local browser/source-to-sink acceptance remains a
separate integration check.

## Checks

Focused backend command:
`python -m pytest backend/tests/test_filing_evidence.py backend/tests/test_research_event_review.py -q`

Focused frontend command:
`node --experimental-strip-types --test tests/filingEvidence.test.ts`

Build command: `npm run build` (TypeScript and Vite).

Local verification on 2026-10-19: focused backend suite passed 28 tests (11 filing,
17 existing event-review tests). Frontend utility and actual TSX interaction
fixtures passed 8 tests, including explicit registration, cancel, duplicate click,
plain-text escaping, exact diff rendering, selection invalidation, late navigation
response and conflict handling. TypeScript + Vite build passed with the existing
bundle-size warning. Browser runtime was not rerun after the environment's known
OS socket denial; component fixtures are not represented as browser acceptance.
