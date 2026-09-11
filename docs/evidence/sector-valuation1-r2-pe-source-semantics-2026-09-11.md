# Sector Valuation 1 R2 · PE source semantics evidence

任务：`PLANNING-PARITY-SECTOR-VALUATION1-R2-PE-SOURCE-SEMANTICS`

日期：2026-09-11

## Evidence boundary

- 本文件只记录公开 Eastmoney / AKShare 来源核验、最小字段样本和本轮代码验证；不保存完整 provider payload。
- 原 `sector-valuation1-live-contract-2026-09-11.md` 保留为 R1 历史记录，但其中 `f9 -> pe_ttm` 的来源结论已由本 R2 明确失效。
- 起始 stable：`feature/research-system-v01@c40d22e4995c132b2aee483d998e39d85bc1ec8a`。
- 任务分支：`luna/sector-valuation-r2-pe-source-semantics`。

## Source qualification

### 1. Public cross-check source

AKShare fixed-source commit `4771e6ea34f6139f226e2bf4fab88ce17579831d` 的
`stock_zh_a_spot_em()` 对 Eastmoney `clist/get` 请求同时包含 `f9` 和 `f115`，并把
`f9` 输出列命名为 `市盈率-动态`。这只证明 `f9` 不是已证明的 TTM 字段；它没有把
`f115` 的语义直接写成 TTM，因此本轮继续做 Eastmoney 自身的数值交叉核验。

核验源码：

- <https://github.com/akfamily/akshare/blob/4771e6ea34f6139f226e2bf4fab88ce17579831d/akshare/stock_feature/stock_hist_em.py>
- <https://akshare.akfamily.xyz/data/stock/stock.html>

### 2. Same-source batch response

获取时间：`2026-09-11T09:59:03.0362208Z`

Endpoint：

`https://push2delay.eastmoney.com/api/qt/clist/get`

受控参数（仅列可复核参数，不保存完整响应）：

```text
pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3
fs=m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048
fields=f2,f9,f12,f14,f20,f23,f100,f114,f115,f116,f117
```

摘要：

```text
source_total = 59527
page_rows = 100
numeric_f9 = 99
numeric_f115 = 99
missing_f115 = 1
identity_value_set_size = 100
repeat_identity_value_set_stable = true
```

公开样本 `300563 / 神宇股份`：

```text
f9   = 118.21
f115 = 81.95
f114 = 68.73
f20  = 5085296143
f23  = 4.51
```

同一查询重复一次后，100 条 `code|f9|f115` identity/value 集合保持一致。该结果
证明 `f115` 是同一个批量 endpoint 实际返回的可用字段，并且与 `f9` 在公开样本中
不是同一个数值；不能继续把 `f9` 静默标记成 `pe_ttm`。

Eastmoney 对 `f115` 缺失使用 `-` 占位（受控样本中 `117246` 返回 `f9=-, f115=-`）。
生产解析继续把 `-`、空值、非法和非有限值变成 `null`；缺失时不回落到 `f9`。

### 3. TTM identity and scale cross-check

使用同一公开证券的 Eastmoney `stock/get` 与官方 F10 单季度数据：

- `https://push2.eastmoney.com/api/qt/stock/get`
- `secid=0.300563`
- `fields=f57,f58,f164,f116,f117`

解析摘要：

```text
stock/get: f57=300563, f58=神宇股份, f164=81.95, f116=5085296142.88
```

官方 F10 `ZYZBAjaxNew?type=2&code=SZ300563` 返回的最近四个单季度归母净利润为：

```text
2026-06-30  PARENTNETPROFIT =  8014354.09
2026-03-31  PARENTNETPROFIT = 13494706.43
2025-12-31  PARENTNETPROFIT = 20677626.11
2025-09-30  PARENTNETPROFIT = 19865592.75
```

```text
trailing_parent_net_profit = 62052279.38 CNY
f116 / trailing_parent_net_profit = 81.951802477...
f115 = 81.95
stock/get f164 = 81.95
```

这在两位小数精度上闭合了 `f115` 的 TTM PE 身份：它是市值除以最近四个
单季度归母净利润的倍数，不是百分比，不需要额外乘除缩放。Eastmoney 页面源码
同时将实时估值入口标为“市盈”，报价页面的帮助文本区分动态、静态和滚动口径；
上述 F10 四季度计算把本批量字段进一步限定到滚动 / TTM 口径，而不是依赖字段编号
猜测。

可复核页面：

- <https://push2.eastmoney.com/api/qt/stock/get?secid=0.300563&ut=f057cbcbce2a86e2866ab8877db1d059&fields=f57,f58,f164,f116,f117&np=1&fltt=2&invt=2>
- <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=2&code=SZ300563>
- <https://quote.eastmoney.com/sz300563.html>

## Corrected production contract

```text
Eastmoney clist/get f9   = dynamic PE; not exposed as pe_ttm
Eastmoney clist/get f115 = same-source TTM PE ratio -> normalized pe_ttm
f115 missing/invalid     = null; never fallback to f9, static PE or zero
PB                        = f23, unchanged
market_cap                = f20, unchanged
industry                  = f100, unchanged
```

The production request remains the existing single full-market batch snapshot with its
existing pagination, throttling and host fallback. No provider, dependency, per-security
HTTP enrichment or new investment authority was added.

## Raw source-to-sink validation contract

The backend and browser fixture now start with Eastmoney-shaped raw fields, call the
production `_map_a_share_row()` parser, and then pass the normalized result through the
existing Sector Industry Context aggregation and UI. The fixture deliberately makes `f9`
and `f115` differ, includes a missing `f115` while `f9` is present, and covers positive,
zero, negative and non-finite TTM values. Existing normalized sector tests remain in place
for zero/negative/missing medians, PB/market-cap coverage, UNKNOWN industry, one snapshot
read, dedupe and RDP failure isolation.

## Validation record

### Controlled production snapshot audit

The production `a_share_snapshot()` path was invoked with `py -3.12` from the backend.
The first full-market attempt was terminated by Eastmoney with a
`RemoteDisconnected` at provider page 36; the production path surfaced that request
failure and no provider payload was saved. One retry completed at
`2026-09-11T10:15:20.531029+00:00`.

Only aggregate counts were retained:

```text
row_count = 5913
unique_code_count = 5913
known_industry_count = 5913
pe_ttm = positive 3927 / zero 0 / negative 1638 / null 348
pb = positive 5512 / zero 0 / negative 53 / null 348
market_cap = positive 5565 / zero 0 / negative 0 / null 348
```

The retry confirms the corrected mapper survives the real full-market batch path. The
transient first-attempt transport failure is retained as an execution note, not hidden
or converted into a data result.

### Local validation

```text
py -3.12 -m pytest -q tests/test_market_snapshot.py tests/test_astock_snapshot_paging.py tests/test_sector_industry_context.py
49 passed

py -3.12 -m pytest -q tests/test_market_cloud.py tests/test_market_breadth.py tests/test_market_snapshot.py tests/test_astock_snapshot_paging.py tests/test_sector_industry_context.py
70 passed

node --experimental-strip-types --test tests/sectorIndustryMatrix.test.ts tests/screenerView.test.ts tests/fullMarket.test.ts
12 passed, 0 failed

npm test
640 passed, 14 suites, 0 failed

npm run build
passed: tsc -b && vite build

npm run test:e2e:sector-industry-context
passed: real FastAPI + production frontend dist + isolated RDP + raw provider-shaped fixture;
desktop and narrow viewport; no pageerror, console error or horizontal overflow

$env:SECTOR_INDUSTRY_E2E_RDP_FAILURE='1'; npm run test:e2e:sector-industry-context
passed: RDP failure remained isolated while sector valuation stayed readable;
desktop and narrow viewport; no pageerror, console error or horizontal overflow

git diff --check
passed
```

The browser harness deliberately supplies raw `f9`/`f115` values through the production
mapper, uses separate normal and RDP-failure fixtures, and asserts the exact TTM-driven
sector outputs. These are local branch results only. This section must not be read as a
stable-branch or Product Reality claim; the task stops at an OPEN / DRAFT / NOT_MERGED
PR.

## Independent Gate — R2

```text
PE_F9_IS_TTM = NO
PE_F115_TTM_SOURCE = VERIFIED_BY_SAME_SOURCE_AND_F10_CROSS_CHECK
TTM_MISSING_FALLBACK_TO_DYNAMIC = NO
TTM_NONFINITE_TO_ZERO = NO
RAW_SOURCE_TO_SINK = REQUIRED_AND_COVERED
PB_AND_MARKET_CAP = UNCHANGED
UNKNOWN_AND_RDP_ISOLATION = UNCHANGED
NEW_PROVIDER = NO
NEW_DEPENDENCY = NO
FORMAL_STATE_WRITES = ZERO
LOCAL_IMPLEMENTATION_GATE = ACCEPT
EXACT_HEAD_CI = PENDING_PR
READY_OR_MERGE = OUT_OF_SCOPE
```

Final PR review / exact-head CI / merge gates are intentionally not claimed by this
evidence file until they actually occur. Ready, merge and Issue #310 closure are outside
this authorization.
