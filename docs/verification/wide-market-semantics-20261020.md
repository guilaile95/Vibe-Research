# Market data semantics repair: P1-05, P1-06, P2-12

## Scope and contracts

- Both stock-relative and sector-industry Full Market readers select the first response's immutable snapshot. Subsequent pages explicitly request that snapshot. Every page must retain snapshot ID, as-of/latest date, dataset, provider, adjustment, and provenance. Missing/changing identity, non-integer or non-progressing offsets, and missing pinned snapshots fail closed through existing unavailable/partial paths. No importer, archive format, historical data, or real research snapshot is changed.
- Global financial metrics carry normalized reporting currency and the original source currency independently of quote/listing currency. A small pure helper is shared with the existing extended-financial adapter. Unsupported or absent currency remains unknown. No FX requests or conversion are introduced.
- The source amount scale remains `PROVIDER_RAW_SCALE_UNVERIFIED`, with no asserted scale-to-currency factor. Both production financial card and AI context preserve raw amounts and visibly state this uncertainty rather than dividing by 100 million and claiming 亿. EPS uses report currency/share. Quote market-cap/turnover formatting is unchanged. Old responses without new metadata remain readable with unknown labels.
- US profit prefers `PARENT_HOLDER_NETPROFIT`; HK profit prefers `HOLDER_PROFIT`. Only absent/None primary values can fall back. Numeric zero and negative values are retained; boolean/nonfinite/invalid values remain missing. Numeric strings follow the existing extended-adapter decimal syntax. Financial metric values are finite before returning JSON.

## Regression coverage

- Synthetic three-stock/two-page and default 1001-stock/1000-page-limit fixtures import two same-date generations (10% versus 100% returns), publish the second after page one, and exercise both real RDP consumers. Stock-relative output must remain zero percentage-point relative return; sector input rows must all retain the first generation's 10% return. Each read must use the same snapshot ID.
- Independent guards cover all seven changed identity fields, absent identities/provenance, invalid/non-progressing offsets, and unavailable pinned snapshots for both consumers.
- Financial tests cover HK CNY/HKD, US non-USD reporting, unknown currency, unverified scale, zero/negative/missing/invalid profit, numeric-string zero, and nonfinite/boolean metrics.
- Frontend tests compile/render the actual production financial-card JSX and actual AI-context expression, in addition to testing shared formatting functions. Old-response unknown semantics and unchanged quote currency are verified.

## Validation

All backend runs use the approved isolated runner after prerequisite isolation commit 5ca0a32, with synthetic fixtures, temporary data roots, and no real provider/model access. No bare pytest or real-user data writes.

- Targeted final fast backend run: 127 passed, 2 real-RDP rotation cases deselected (run separately with a 900-second budget).
- Extended public-research/factor-validation/global-metrics regression run: 67 passed. Final metric refinements additionally covered by the 127-pass run.
- Frontend targeted regression: 21 passed, including actual production card/AI rendering and existing financial/relative-view regressions.
- TypeScript noEmit: passed. Vite production build: passed, with the existing bundle-size advisory.
- Real RDP rotation and original targeted suite: 122 passed in 272.64 seconds, including both the three-stock and default 1001-stock fixtures, each exercising both consumers. The final 127-pass fast run covers subsequent added edge cases and metric normalization; its two deselected rotation cases are the same cases already passed in the 900-second-budget run. No coverage was removed.

Limits: no live-provider schema/amount-unit verification, FX validation, visual browser acceptance, or full cross-platform suite in this lane. Root integration owns independent review and final CI; no deployment.

### Test selections

Run backend selections through the approved isolated runner, not bare pytest:

- `tests/test_global_metrics_semantics.py tests/test_context_snapshot_pinning.py tests/test_stock_relative_context.py tests/test_sector_industry_context.py tests/test_gstock_identity.py -q -m "not live"` (900-second budget; final fast check adds `-k "not real_rdp_rotation"`).
- `tests/test_global_metrics_semantics.py tests/test_extended_public_research.py tests/test_factor_validation.py -q -m "not live"`.
- Frontend: `node --experimental-strip-types --test tests/globalFinancials.test.ts tests/globalFinancialsRender.test.mjs tests/financial-ai-context.test.ts tests/financial-zero-render.test.mjs tests/stockRelativeContextView.test.ts`.
- Frontend compiler/bundler: `tsc -p tsconfig.json --noEmit` and `vite build`.
