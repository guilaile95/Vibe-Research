# Core-provider replay contracts

**All fixtures here are synthetic constructed data, not actual recorded HTTP
responses. Passing these tests does not qualify a real provider. The live-provider
acceptance gate remains `BLOCKED_NOT_EVALUATED`.**

## Scope and provenance

The initial corpus was constructed from the existing repository parsers and
`test_tencent_kline_contract.py` / `test_astock_financial_health.py` examples.
The relevant checked-in fixture/test locations were inspected; no authorized,
provenance-backed raw recordings for these three paths were found. Existing
product/page snapshots are not promoted into raw-provider evidence.

No live request, credentials, account/portfolio data, external SDK replacement,
or imported third-party framework/source is used. The public security codes are
routing examples; all names, prices, dates and financial values are constructed.
No inference about real market data should be made from them.

| Fixture | Injected boundary | Production path exercised |
| --- | --- | --- |
| `tencent_quote.json` | HTTP body encoded as GBK | `tencent_quote` → `_fetch_gtimg` → `_parse_gtimg` |
| `tencent_kline.json` | HTTP JSON response | `unadjusted_bars` → `fetch` |
| `ths_financials.json` | AkShare DataFrame records | `financials(include_health=True)` summary and statement normalization |

The financial fixture is **SDK-boundary replay, not raw upstream HTTP replay**.
It cannot catch AkShare HTTP parsing regressions. Quote units are explicit
`amount_wan` / `mcap_yi`; K-line ordinary lots convert to shares once while STAR
shares remain unchanged; financial summary unit strings remain strings and
statement numeric values are not rescaled.

Cases carry a stable ID and diagnostic `reason`. They cover normal/empty input,
missing dates, renamed/truncated fields, invalid units or numbers, partial-batch
rejection, and HTTP 429. Financial optional-table failures retain the summary,
mark quality partial and expose missing fields / `cashflow_unavailable`. Missing
publication dates stay unknown with PIT support false; report-period dates never
become announcement dates. This suite does not claim to validate historical PIT
admission or every quote/K-line downstream consumer.

## Run offline

From the repository root with the project dependency-equipped Python:

    python -m pytest backend/tests/test_core_provider_replay.py -q

The suite injects only transport/SDK boundaries and freezes the K-line clock.
It blocks unexpected requests, urllib calls, DNS resolution and socket connects;
no recorded response is fetched while testing. Backend conftest redirects user
storage into temporary directories. The Python guards are test protections,
not a hostile-code/network-namespace sandbox.

## Future approved recording procedure (not performed)

This is the admission procedure for a subsequent **explicitly authorized** capture;
this change neither authorizes nor automatically performs it:

1. Obtain approval naming the public provider, endpoint, public symbol, capture
   window, request budget and any data transmitted. Do not use credentials,
   cookies, private holdings or authenticated provider endpoints in this corpus.
2. Capture only the approved public response body and status at the existing
   transport boundary. Do not save request headers, environment values, cookies,
   full sessions or token-bearing URLs. For financials, clearly choose either
   SDK records or a separate upstream-HTTP test; never label SDK records raw HTTP.
3. Review locally for secrets and personal data before adding a fixture. Discard
   unsafe bodies rather than publishing them. Retain only necessary public fields;
   document redactions and their effect on fidelity. Do not fabricate a capture
   timestamp, change synthetic provenance, or describe a modified response as an
   unmodified recording.
4. Add a separate fixture in this same case format, with provenance
   `kind: recorded_public_response`, `boundary`, provider/endpoint identity,
   `captured_at` (UTC), approval reference, SDK version where applicable,
   sanitization notes, and SHA-256 of the sanitized checked-in payload. Have a
   reviewer verify these against the capture evidence. Metadata alone is not
   proof of a recording. Keep constructed mutations in separate cases labelled
   `synthetic_constructed` with the original fixture reference.
5. Parameterize the existing replay tests for that fixture, with expected values
   independently checked against the body. Keep 429/error and drift mutations
   separate from actual observations. Run the existing offline regressions.
6. Report recorded replay separately from live availability, latency, coverage
   and sustained reliability. Do not unlock the real-provider acceptance gate
   from a passing replay suite, even after recordings have been added.

No capture utility is enabled by this batch: capture needs the above approval and
review. This avoids a fixture refresh command silently making live requests.
