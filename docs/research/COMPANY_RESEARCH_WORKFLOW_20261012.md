# Bounded six-stage company research

The existing StockData page now offers explicit public evidence capture and a separate,
confirmed six-stage API research run: profile, financials, estimates, valuation, risk,
report. All stages consume one immutable, hashed input bundle. No model-selected tools,
subscription-runtime expansion, formal thesis/evidence writes or trade actions are added.

## Source scope

A shares reuse individual_info, financials, full_valuation, tencent_quote, announcements
and lockup_expiry. HK/US reuse the existing market-identity-checked global company
aggregate; HK also reuses cashflow. Missing HK/US estimates and risk source families are
explicit UNSUPPORTED inputs, not zero facts or comprehensive international coverage.
The adapters expose their full normalized return, **not raw HTTP response bytes**.
Capture time, source time (often unknown), input hash and source availability are distinct.
This implementation is workflow parity, not proof of complete upstream provider parity.

## Budget and authority

Capture is explicit. Generate confirms the configured API destination, model and maximum
six calls with 2500 output tokens each; no automatic retry. Existing API transport owns
cancellation. Each completed stage must have valid schema and existing AVAILABLE evidence
IDs; missing-source disclosures are also derived by code. Citation validity is not factual,
numeric or semantic verification. Every report remains NON_AUTHORITATIVE_AI_DRAFT and
numeric_claim_verification=NOT_EVALUATED. No calculation DAG or semantic truth gate is
claimed. No cash, holdings, trade ledger or account inputs enter the fixed source plan.

## Records and recovery

Frozen bundles and research run records live in a scoped local SQLite store under the
existing VR_DATA_DIR. They are not an alternative formal ledger or task runtime. A single
owner token can transition RUNNING to a terminal state. Completion retains all six validated
stages and hashes; cancellation/failure retain metadata and count only, never partial model
text labelled as a report. Read-only routes do not initialize files. Completed restore checks
bundle/stage/result lineage and fails closed on corruption. Persisted RUNNING after a process
crash is not a promise that a background worker is active. The UI offers an explicit separate
save into existing Notes; generated reports are never automatically published.

## Verification boundary

Tests use synthetic source adapters and model streams. No live provider/model call, browser
execution or physical deployment was performed during authoring. Actual-page browser CI is
required on the integrated candidate. Other provider families and advanced calculations
remain separately assessed under the endpoint applicability ledger.

## Source review corrections
Read-only restore uses the existing bounded private SQLite image helper, one frozen image for records and bundles, byte caps before payload fetch, strict schemas for every state and SQL column binding, followed by unchanged-source verification. It does not open source SQLite in read-only mode or create sidecars. Empty usable evidence prevents all model calls. Capture owns one of two slots until its synchronous source function exits; the request deadline is 90 seconds. Cancellation/deadline prevents subsequent source calls and persistence but cannot forcibly stop an already-running synchronous adapter. Existing provider timeout behavior remains applicable; a blocked adapter retains its slot rather than spawning unbounded work.

Returned adapter security identity must be present and match the subject. Existing normalized CN financial/announcement/lockup outputs without such identity are preserved but marked ERROR and cannot be cited as AVAILABLE; closing this source contract gap requires qualified raw adapter receipts. Profile identity, valuation identity and keyed quote returns are validated. This is a disclosed adoption gap, not complete upstream six-stage input parity. Source times are validated when present and never synthesized from capture time. Persisted RUNNING means an unfinished historical record, not proof of a live task.

## Qualified archive hookup
The explicit archive cutoff is passed to `archive_company_plan(market, symbol, as_of)` once. Its detached readers consume one validated immutable archive image; generation never reloads it. Historical cutoffs suppress all current native readers. Present-day native inputs remain separately labeled and cannot stand in for missing qualified archive inputs.

The six critical input families have concrete raw adapters and archive receipts: `cn_quote_ref`, `cn_financials_ytd`, `cn_consensus`, `global_quote_ref`, `global_financials_pit`, `yahoo_consensus`. Envelopes bind exact source/subject/cutoff, source capture timestamp, immutable raw artifact hash, qualification/status and full normalized block. Invalid/missing/late sources remain explicit gaps. All-zero or negative source values are preserved. An entirely unavailable bundle never starts the model.

These are qualified alternative inputs, not claims of identical upstream schemas. CN financial data is report-period YTD; unknown monetary raw scales are `PROVIDER_RAW_SCALE_UNVERIFIED` with null conversion factor. It is not automatically a quarterly or TTM series. Global financial data is current-vintage notice-date filtered, with restatement/overwritten-notice risk; no historical-vintage PIT guarantee exists. Consensus is analyst expectation in reporting currency, not company promise. Quote timestamps and benchmark reference days do not certify an official exchange holiday calendar. Numeric calculation correctness remains NOT_EVALUATED.

UI shows cutoff, original source capture, raw hash, synthetic-fixture indication and the above limitations. The real registered API golden tests traverse synthetic producer bytes→FactLake→archive qualification→capture→six owned model-stub stages→strict restore for CN/US/HK, including missing, wrong identity, malformed fiscal period, future-to-cutoff quote, cutoff mismatch and cancellation cases. No live providers/models or local browser ran.
