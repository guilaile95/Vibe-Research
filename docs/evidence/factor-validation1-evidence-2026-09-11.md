# Factor Validation v0.1 — implementation evidence

任务：`PLANNING-PARITY-FACTOR-VALIDATION1`

本文件记录本轮 bounded implementation、source-to-sink contract 和本地验证证据。GitHub PR、exact-head CI、merge commit 与 post-merge CI 以 live GitHub 和 #203 最终 recovery coordinate 为准，不在此文件中预填未知坐标。

> Historical correction: PR #307's initial implementation allowed stale as-of Full Market rows into a factor-date cross-section. The R2 exact-date cross-section correction is recorded in `factor-validation1-r2-exact-date-cross-section-2026-09-11.md`; this v0.1 evidence remains the historical implementation record.

## Scope

- source 只使用现有 RDP Parquet / DuckDB 和 `query_full_market(as_of=T, latest=false)`。
- registry 只有现有透明 Full Market metrics：`return_5d`、`return_20d`、`return_60d`、`close_vs_ma20`、`close_vs_ma60`、`volume_ratio_20d`。
- 每次请求只运行一个 Factor；forward windows 固定为 5 / 20 条已存储观测。
- 结果是只读的 cross-sectional Spearman rank IC、average-rank tie 处理，以及 top 20% minus bottom 20% 的描述性 forward-return spread。
- `formal_state_write.performed = false`；没有新增 provider、数据依赖、账户/持仓/研究/交易写入或投资 authority。

明确不包含完整回测、成交/成本/滑点、PnL/NAV、grid calibration、Walk-Forward、factor weight、composite score、BUY/SELL、recommendation 或 Product Reality。

## Factor-value parity

Factor value 不在新模块中重新计算。对每个 factor date，代码通过现有 Full Market contract 取得同一 artifact、同一 security、同一 `source_metric`，并直接将该字段作为 factor value；response 的 parity mode 为 `DIRECT_SOURCE_METRIC_REUSE`。因此不会产生第二套 return / MA / volume-ratio 语义。

本地 parity test 对六个 registry factor 都用同一 fixture，将 Full Market 返回的 source metric 替换为有区别的 sentinel values，再检查 IC 输入收到的值逐项相同；这不是“两套算法碰巧算出同一个结果”的断言。

## Statistical and temporal contract

- IC 是日期 T 内不同证券之间的 Spearman rank correlation，不是单证券时间序列相关。
- Tie 使用 `AVERAGE_RANK`；pair 少于 2、factor 恒定、forward return 恒定或 rank variance 为零时 `rank_ic = null` 并给出 reason。
- 真实 `0.0` 保留为零；null 不转换为零。Bucket spread 同样区分真实 0 与 null。
- forward return 为 `future_close / current_close - 1`，窗口按 5 / 20 条已存储观测计，不称严格交易日历 T+5 / T+20。
- Factor value 使用 `query_full_market(as_of=T, latest=false)` 的 T 截止语义；未来行只用于 forward outcome。历史扫描最多读取 250 个 factor dates，并暴露 requested/effective range、artifact coverage、attempted/evaluated、immature、excluded 与 truncation。
- `RDP_OBSERVED_CROSS_SECTION` 是当前 artifact 在日期 T 的 observed cross-section，不是 point-in-time historical constituent 或 historical investable universe；`HISTORICAL_VALIDITY = NOT_PROVEN`。
- RDP `ADJUSTMENT = UNADJUSTED`，除权除息影响未被调整。High/Low 只代表描述性分桶统计，不代表交易策略或投资收益。

## Browser vertical

使用 61 个 security、90 个日期的 deterministic isolated RDP artifact（60 个完整序列，另有一个提前结束的序列），覆盖正 IC、负 IC、tie、factor null、immature forward window、正 spread、真实零 IC 和 null 展示。

路径为：`/signals` → `因子有效性` → 选择 factor / 日期范围 → `运行因子验证` → 5 / 20 observation → 展开历史横截面。验证链路是真实 FastAPI + production frontend build + fixture adapter，Factor 计算未 mock。Desktop 使用 1440×900，narrow 使用 390×844；检查了 parity、observed-universe / UNADJUSTED limitation、零与 null 展示、页面无 document-level overflow、无 pageerror / console error。浏览器专用插件当前不可用，使用仓库现有 Playwright regular fallback；截图保存在仓库外的临时 evidence 目录，不进入数据或 Git。

## Local validation

基线：`feature/research-system-v01@c7d306778e5e0417638ee1e5d77eec4b91959b11`。实现工作在 isolated worktree `luna/factor-validation-v01`；Owner checkout 未进入、未清理、未覆盖。

```text
backend factor tests: 6 passed
RDP / Historical Signal Validation / Pattern / Screener regressions: 60 passed
frontend focused + Signals / Pattern / Screener tests: 639 passed, 0 failed
production build: passed (tsc -b && vite build)
Factor browser E2E: passed
git diff --check: passed
```

主要命令：

```text
py -3 -m pytest tests/test_factor_validation.py -q                 # backend: 6 passed
py -3 -m pytest tests/test_research_data_plane_full_market.py tests/test_research_data_plane_patterns.py tests/test_historical_signal_validation.py tests/test_screener.py tests/test_screener_api.py -q  # 60 passed
npm test -- --test-name-pattern="factor validation|historical validation|Full Market|result grouping"  # 639 passed
npm run build
npm run test:e2e:factor-validation
git diff --check
```

## Independent Gate

```text
FACTOR_SOURCE = EXISTING_RDP_ONLY
FACTOR_REGISTRY = EXISTING_TRANSPARENT_METRICS_ONLY
FACTOR_VALUE_PARITY_WITH_FULL_MARKET = PROVEN
IC_METHOD = CROSS_SECTIONAL_SPEARMAN
TIE_RANKING = AVERAGE_RANK
FORWARD_WINDOWS = 5_AND_20_STORED_OBSERVATIONS
HIGH_LOW_BUCKET = TOP_20_PERCENT_MINUS_BOTTOM_20_PERCENT
HIGH_LOW_IS_TRADING_STRATEGY = NO
FUTURE_LEAKAGE = NO
HISTORICAL_UNIVERSE_AUTHORITY = NOT_AVAILABLE
RDP_ADJUSTMENT = UNADJUSTED
HISTORICAL_VALIDITY = NOT_PROVEN
PER_SECURITY_HTTP_N_PLUS_ONE = NO
NEW_PROVIDER = NO
NEW_DEPENDENCY = NO
FACTOR_WEIGHT_AUTO_UPDATE = NO
BLACK_BOX_SCORE = NO
BUY_SELL = NO
FORMAL_STATE_WRITES = ZERO
PRODUCT_REALITY_DAY_1 = NOT_STARTED
```

本地 evidence 支持 Gate = `ACCEPT`；Ready、ordinary merge 和 post-merge closure 仍以 exact-head / exact-stable live GitHub 证据为准。
