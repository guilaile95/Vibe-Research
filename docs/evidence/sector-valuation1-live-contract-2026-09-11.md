# Sector Valuation 1 · Live Source and Vertical Evidence

> Historical R1 evidence only. The `f9 -> pe_ttm` source conclusion in this file is
> superseded and invalidated by `sector-valuation1-r2-pe-source-semantics-2026-09-11.md`:
> AKShare identifies Eastmoney `f9` as dynamic PE. Do not use the R1 `f9` mapping or its
> aggregate counts as TTM evidence.

任务：`PLANNING-PARITY-SECTOR-VALUATION1`

日期：2026-09-11

## Live starting truth

- Stable branch：`feature/research-system-v01`
- Live starting stable：`29ba163012b24c1f5bbc014db14469f0052a5d2a`
- 本轮在独立 worktree `luna/sector-valuation-v01` 执行；Owner dirty checkout 未用于 checkout、pull、reset、clean、stash、restore 或覆盖。
- #203 live authorization：`issuecomment-5626697539`
- 本轮没有新增 provider、endpoint、依赖、投资 authority 或 Formal state write。

## Live Eastmoney snapshot contract audit

使用生产 `backend/astock.py` 的 `a_share_snapshot()` 实际读取当前快照。该 mapper 的既有字段映射保持不变：

```text
pe_ttm    = Eastmoney f9  -> _optional_float
pb        = Eastmoney f23 -> _optional_float
market_cap= Eastmoney f20 -> _optional_float
industry  = Eastmoney f100
```

本次读取只输出脱敏统计，没有保存或写入完整 provider payload。最近一次成功 audit 的计数如下：

```text
total_rows          = 5912
unique_code_count   = 5912
industry_known_count= 5912

pe_ttm: positive=4150, zero=0, negative=1415, null=347
pb:     positive=5512, zero=0, negative=53,   null=347
market_cap: positive=5565, zero=0, negative=0, null=347
```

两个独立 audit 读取均成功返回合法列表；当前样本证明了 PE/PB 的正值、负值与缺失字段确实存在，且 market cap 缺失也确实存在。既有 `_optional_float()` 单元测试继续证明缺失、`-`、不可解析值为 `null`，真实 `0` 保留为 `0.0`；mapper 没有把 `null` 伪造成 `0`。本轮没有修改 `a_share_snapshot()` 的经济含义。

## Implemented contract

Sector Context schema 升为 `sector_industry_context.v0.2`，保留既有：

```text
membership_semantics         = CURRENT_MEMBERSHIP_SNAPSHOT
historical_membership_validity= NOT_PROVEN
crowding_semantics           = TRANSPARENT_PARTICIPATION_PROXY_ONLY
```

每个当前行业成员在已有一次 snapshot 归一化阶段保留 `pe_ttm`、`pb`、`market_cap`。同一证券只使用第一条有效 code 的同一 snapshot row，不进行第二次 provider lookup。

估值语义固定为：

```text
CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY
```

PE/PB 的 `observed_count` 只计 finite source value；`missing_count` 为当前成员数减去 observed。正值、0、负值分别计数；median 只对正值计算，奇数/偶数均使用 deterministic `statistics.median`。有 observation 但没有正值时，`median_status=NO_POSITIVE_VALUES` 且 median 为 `null`，不会把 0 当作缺失或 median。

每个 valuation metric 输出 `NORMAL` / `PARTIAL` / `UNAVAILABLE`，另输出 observed/positive coverage。positive coverage 的分母显式为 `CURRENT_MEMBER_COUNT`。market-cap 只做质量覆盖：有效正市值成员计数和总额，以及每个正 PE/PB metric 的正市值覆盖；分母是全部当前成员的有效正市值，分母不存在时返回 `null`。没有 weighted PE/PB、composite、score 或 attractiveness 结论。

每个 industry envelope 还明确输出：

```text
historical_percentile.status              = NOT_AVAILABLE
sector_index_valuation_authority.status   = NOT_AVAILABLE
```

没有 valuation trade date 或 official close date；顶层只提供 `snapshot_fetched_at`。UI 明示这是 Eastmoney 当前快照及获取时间，而不是历史估值或行业指数估值。

RDP 历史指标和 snapshot valuation 在后端保持独立：RDP 不可用时 current-membership valuation rows 仍构建；valuation 字段缺失时 membership、breadth、participation 与 RDP 指标不被一起失败。UNKNOWN 成员继续单独归入 `UNKNOWN`。

## Browser source-to-sink evidence

复用现有 `frontend/tests/e2e/sector-industry-context.browser.mjs` vertical，使用真实 FastAPI route、生产 frontend build 与隔离 snapshot/RDP fixture。fixture 覆盖：

```text
电子：PE 10/20/0，PB 1/2/-1，含有效和无效 market cap
医药：PE 5/缺失，PB 1/3，产生 partial valuation
传媒：负 PE、缺失 PB
UNKNOWN：0 PB、缺失 PE
```

正常 RDP 场景通过：电子 PE 正值 median=15、PB 正值 median=1.5，0/负值/缺失分开显示，UNKNOWN 保留，PE/PB 覆盖与市值覆盖可见。另以同一 vertical 的 `SECTOR_INDUSTRY_E2E_RDP_FAILURE=1` 隔离 fixture 运行：真实 API 的 historical status 为 unavailable，但 valuation rows 仍返回，UI 仍显示矩阵与当前成员 PE/PB 分布。

两个场景均覆盖 desktop `1440×900` 与 narrow `390×844`，检查了无 pageerror、无 console error、无 document overflow，并验证现有排序和 `/market-cloud` 入口未被破坏。浏览器插件在当前环境不可用，因此使用仓库已有 regular Playwright Chromium 路径；不是跳过浏览器验收。

## Local validation

```text
backend Sector Industry Context focused tests = 11 passed
backend sector/RDP/market regressions       = 60 passed
frontend focused matrix tests               = 3 passed
frontend sector/Screener regressions        = 21 passed
production build (tsc -b && vite build)     = passed
Sector Industry browser E2E, normal RDP     = passed
Sector Industry browser E2E, RDP failure    = passed
git diff --check                             = passed
```

一次完整 backend 非 live suite 也被执行：`7710 passed, 11 skipped, 1 failed`。唯一失败是 Windows `WinError 10055` socket 资源耗尽，发生在与本轮无关的 `test_formal_thesis_acceptance.py::test_g_revision_timeline`；该测试在新进程单独重跑为 `1 passed`。这不是本轮 Sector 变更失败，但完整 suite 的第一次运行不被记为全绿。

## Independent Gate — pre-PR local result

```text
VALUATION_SOURCE = EXISTING_EASTMONEY_A_SHARE_SNAPSHOT_ONLY
SNAPSHOT_FIELDS = PE_TTM_F9 / PB_F23 / MARKET_CAP_F20 / INDUSTRY_F100
LIVE_SOURCE_CONTRACT = PROVEN
SNAPSHOT_CALLS_PER_BUILD = ONE
PER_SECURITY_VALUATION_HTTP = NO
VALUATION_SEMANTICS = CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY
PE_NONPOSITIVE_VALUES = PRESERVED_AND_COUNTED
PB_NONPOSITIVE_VALUES = PRESERVED_AND_COUNTED
MISSING_VALUES_AS_ZERO = NO
POSITIVE_MEDIAN = TRANSPARENT
RDP_FAILURE_ISOLATES_FROM_VALUATION = YES
HISTORICAL_VALUATION_PERCENTILE = NOT_IMPLEMENTED
SECTOR_INDEX_VALUATION_AUTHORITY = NOT_AVAILABLE
CHEAP_EXPENSIVE_CLASSIFICATION = NO
BLACK_BOX_SCORE = NO
BUY_SELL = NO
NEW_PROVIDER = NO
NEW_DEPENDENCY = NO
FORMAL_STATE_WRITES = ZERO
```

The local source-to-sink evidence supports `INDEPENDENT_GATE = ACCEPT`. Exact-base recheck, Draft PR review, exact-head CI, Ready/ordinary merge, post-merge exact-stable CI, launcher applicability and #203/Notion closure remain separate delivery gates and are not represented here as complete.
