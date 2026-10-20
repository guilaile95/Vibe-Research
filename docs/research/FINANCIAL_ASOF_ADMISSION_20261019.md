# Financial release-time admission — 2026-10-19

## Scope and remaining gap

This slice adds conservative, structured release-time diagnostics to the existing
financial shadow query. It does **not** enable financial PIT queries, register a
trusted provider, or resolve `REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED`. Current
financial retrieval and report-period capability evaluation retain their behavior.
`FINANCIAL_DATASET_SPEC.point_in_time_supported` remains false.

`query_financial_indicators(as_of=...)` now evaluates the stored observations using
`evaluate_financial_time_admission`, then raises `FinancialAsOfUnavailable` (a
`DataContractError`) with immutable structured admission results. The production
route has no exact-version publication evidence, so it returns UNKNOWN diagnostic
reasons, never USABLE. An empty history reports missing observations rather than
pretending that no reports existed at that historical instant.

No schema, provider response, canonical fact, frozen decision bundle, report
snapshot, or publication artifact is rewritten. Current latest/all/publication
queries retain their behavior. Pinned canonical publications remain unchanged
after later corrections and after rejected historical queries.

## Admission rules

- Historical release eligibility requires a reviewed authority route and evidence
  bound to dataset, provider/endpoint, security, report period, observation ID,
  exact source payload hash, revision ID, and data version
- The private authority registry is empty. Neither provider payloads nor function
  or query arguments can supply a trusted-authority allowlist. Synthetic tests
  patch the private registry only within isolated test scope
- The release timestamp must describe that exact payload/revision. An earlier
  original filing date cannot authorize a later correction
- Report periods, date-only `ann_date`, capture/observation/effective times, and
  quarter-plus-45/year-plus-90 estimates never substitute for publication time
- UTC timestamp parsing reuses `data_contracts`. Naive, invalid, date-only and
  noncanonical offset timestamps remain unknown; adapters must explicitly
  normalize supported source timezone semantics before admission
- Release after the cutoff is excluded; equality is included. Missing authority
  or time remains unknown. Subject/version disagreement is excluded
- TEMPORALLY_ADMISSIBLE describes only exact-version source release eligibility.
  A later local capture is not proof of availability in an earlier frozen bundle
  and does not grant canonical or report-period applicability authority

Future integration must independently establish authoritative exact-version
publication provenance, trustworthy source timezone semantics, appropriate
historical revision selection, and dataset/report-period applicability. Adding a
source-ref string alone is insufficient and not exposed as an API option.

## Independent semantic references

Reviewed 2026-10-19:

- [Qlib PIT documentation](https://qlib.readthedocs.io/en/stable/advanced/PIT.html):
  publication date and accounting period are separate, and later amendments must
  not leak into earlier historical views
- [TradingAgents changelog](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md):
  dated-run and as-filed financial-data constraints informed the historical
  cutoff, subject-binding, and unavailable-source test scenarios

Implementation and synthetic fixtures were independently written for existing
Vibe-Research contracts. No upstream source code or fixtures were copied, no
upstream runtime/package was added, and these references are not evidence that
Vibe-Research has a trustworthy live historical financial source.

## Offline validation

Run from the repository root with the existing backend test environment:

```sh
PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_financial_asof_admission.py \
  backend/tests/test_financial_indicator_shadow.py \
  backend/tests/test_critical_data_financials_adapter.py \
  backend/tests/test_financial_indicator_multiprocess_s2.py
```

Coverage includes future/unreleased versions, exact cutoff, late corrections,
missing/invalid/timezone timestamps, subject and payload binding, forged trust,
current-view preservation, pinned publication preservation and the actual shadow
query caller. Tests use temporary FactLake instances and synthetic payloads; no
live provider data, model calls, credentials, trading or production migration.
