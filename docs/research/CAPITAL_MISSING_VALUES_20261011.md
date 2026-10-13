# Financing and shareholder values: unknown versus zero

## Source and scope

This is a selective compatibility repair, informed by Simon's original
[`eastmoney.py` at d643728e79b955dfdcdcd8b0dd362bd7c90c35c8](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/eastmoney.py#L343-L371).
The original margin and holder adapters use `r.get(field)` rather than a zero
default. Its margin comment explicitly warns against reporting omitted RZYE as
zero financing balance. The file was read at the pinned commit, not executed.
The project's root MIT license retains Simon's attribution.

Local adaptation covers exactly six numeric margin fields and three numeric
holder fields. It reuses the existing optional finite-number parser with a
scoped boolean/overflow guard; the shared parser is unchanged. It preserves
true zeros, finite numeric strings (normalized to numbers), negative finite
values, dates, units, field names, arrays, projection limits and ordering.
It does not add upstream `rqchl` or `change_num`, change providers, introduce
new schemas, or change risk scoring and trading authority.

Upstream raw `r.get` does not itself establish nonfinite normalization.
Rejecting malformed numeric values here is a locally verified compatibility
requirement, not an assertion that upstream implements it or that the live
provider currently sends these values.

## Proven before/after chain

Self-authored synthetic provider rows were run through the actual local
adapter, HTTP TestClient, AI tool handler and crowding evaluator. Sockets were
blocked before imports and persistence used a temporary data directory.

| Input / sink | Before | After |
|---|---|---|
| Omitted numeric field → adapter/API/tool | Numeric 0 | JSON null |
| Explicit null → financing/count cards | `0.00 亿` / `0` | `—` |
| True zero → cards | Numeric zero | Numeric zero retained |
| Blank string → cards | Numeric zero | `—` |
| NaN/Infinity → API | HTTP 500 | HTTP 200, field null |
| [100, missing] financing → crowding | SAFE, -0.2, confidence 70, “下降100%（杠杆去化）” | NEUTRAL, skipped, confidence 0 |
| [100, actual 0] financing → crowding | SAFE, -0.2 | Unchanged |

The old adapter's fabricated final zero could therefore supply an explicit
false deleveraging conclusion, not merely a misleading label. Existing
crowding null filtering already handles unknown values; no evaluator source
change was needed. The top-risk result remains a research analysis contribution,
not evidence that this defect changed a formal decision or trade.

For shareholders, the old adapter manufactured zero holders and zero period
change from absence. The tool description invites using these counts as
concentration/dispersal evidence. Tool payload distortion is proven; an actual
model-generated inference was not tested.

## Verification

- 164 focused backend cases passed: new capital source-to-sink contract tests,
  existing top-risk tests, safe API failure tests and dividend unit contracts
- 14 stock-data evidence helper/wiring tests passed
- Frontend TypeScript and production build passed
- Added mocked-browser assertions for missing, zero and blank financing/count/
  ratio cards to the existing StockData smoke harness
- Initial browser launch could not proceed: the container's Chromium process
  singleton socket was denied. This is not a browser-runtime pass

Focused commands (run with temporary `VR_DATA_DIR` and an outer socket guard):

```sh
cd backend
python -m pytest -q tests/test_capital_missing_values.py tests/test_top_risk.py tests/test_api_safe_failures.py tests/test_dividend_unit_contract.py
cd ../frontend
node --experimental-strip-types --test tests/stockDataEvidence.test.ts
npm run build
npm run test:e2e:smoke
```

No full backend suite, live market/provider sample, real model, credential,
publication, merge or deployment was used for this verification. Live provider
field availability and ongoing real-market reliability remain unverified.
