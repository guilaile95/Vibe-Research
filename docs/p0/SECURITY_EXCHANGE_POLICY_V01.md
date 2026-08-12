# Security Exchange Policy v0.1

**Status:** implementation contract

**Authority role:** six-digit A-share `security_code` to canonical exchange routing

**Schema version:** `security_exchange_resolution.v0.1`

**Policy version:** `security_exchange_policy.v0.1`

## Boundary

This policy answers one question only: which mainland exchange owns the officially
allocated A-share stock code segment containing a six-digit code.

It does **not** establish that a security exists, is listed, active, tradable, in the
product universe, or covered by market data. A range hit is exchange routing, not an
instrument record. Listing status and data availability require separate authorities.

Policy selection is explicit through `policy_version`. There is no default-latest,
`as_of`, wall-clock selection, provider lookup, network access, database, or filesystem
I/O in the runtime policy.

## Official sources and frozen segments

### SSE

- Source: [SSE Securities Code Segment Allocation Guide, 2026 second revision](https://www.sse.com.cn/lawandrules/guide/stock/jyglywznylc/zn/c/c_20260713_10825354.shtml), published 2026-07-13.
- A-share stock segments routed to `SSE`: `600000–600999`, `601000–601999`,
  `603000–603999`, `605000–605999`, `688000–688999`.
- Explicit exclusions include `689000–689999` depositary receipts and
  `900000–900999` B shares. Funds, bonds, repos, asset-backed securities, indices,
  warrants, and other allocated products are not admitted by this policy.
- Confidence: `PROVEN`.

### SZSE

- Source: [SZSE Securities Code Range Table, March 2026 revision](https://www.szse.cn/marketServices/technicalservice/doc/P020260306733846760075.pdf), published 2026-03-06.
- A-share stock segments routed to `SZSE`: `000000–000999`, `001200–001999`,
  `002000–004999`, `300000–309799`.
- Explicit exclusions include `001001–001199` main-board depositary receipts,
  `309800–309999` ChiNext depositary receipts, `200000–209999` B shares,
  `158000–159999` ETFs, and `399000–399999` indices. Other funds, debt products,
  repos, asset-backed securities, voting codes, options, and business codes are not
  admitted by this policy.
- Confidence: `PROVEN`.

### BSE

- Current-code source: [BSE Issuance and Listing Guide No. 2](https://www.bse.cn/fxrz_list/200021628.html), published 2024-04-19 and effective 2024-04-22.
- Code-category source: [BSE/NEEQ Securities Code and Abbreviation Compilation Guide](https://www.bse.cn/jygl_list/200021626.html), published 2024-04-19 and effective 2024-04-22.
- Transition source: [BSE existing-listed-company code cutover notice](https://www.bse.cn/important_news/200026735.html), published 2025-09-12 and effective 2025-10-09.
- Exact legacy source: [BSE old/new code mapping](https://www.bse.cn/code_mapping/200025792.html), published 2025-09-12.
- Current common-stock allocation routed to `BSE`: `920000–920999`.
- The 248 legacy codes in the official old/new mapping are individually frozen by
  the implementation and routed to `BSE`. No broad `4xx` or `8xx` range and no
  suffix/prefix transformation is permitted. The mapping proves exchange routing only;
  this policy does not expose or infer issuer lineage.
- Confidence: `PROVEN`.

## Result contract

The public resolver accepts an exact six-character ASCII digit string and an explicit
policy version. It returns a detached deterministic mapping with:

- `schema_version`
- `policy_version`
- `security_code`
- `exchange_resolution_state`: `RESOLVED`, `NOT_RESOLVED`, or `NOT_EVALUATED`
- `exchange`: `SSE`, `SZSE`, `BSE`, or `None`
- `authority_ref`
- `source_refs`

Malformed input is rejected rather than coerced. A valid six-digit code outside the
officially frozen stock segments returns `NOT_RESOLVED`; it is never guessed. An
unknown non-empty policy version returns `NOT_EVALUATED` and does not select a latest
policy implicitly. Missing, empty, non-string, or whitespace-padded policy versions are
validation failures.

Resolved outputs contain no `exists`, `listed`, `active`, `tradable`, `usable`, data
coverage, Tushare `ts_code`, or provider suffix field.

## Anti-rewheel decision

Repository helpers in BK11, Tushare daily/financial adapters, Tencent/Eastmoney symbol
formatters, and Campaign validation are `REJECT_AS_AUTHORITY`. They encode provider
aliases, transport conventions, narrower historical scopes, or syntax validation; none
is a public versioned exchange-routing authority. They may consume this policy later,
but they do not define or override it.

## Change discipline

The v0.1 segment set and source references are immutable. An official rule change must
create a new explicit policy version; it must not silently mutate v0.1. Provider alias
translation belongs to a later provider-contract adapter and is not part of SER1.
