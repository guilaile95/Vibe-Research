# Pattern Discovery v0.1 证据记录

任务：`PLANNING-PARITY-PATTERN-DISCOVERY1`

日期：2026-09-10

> Correction note: this v0.1 evidence recorded the PR #303 drifted `>= 2.0` volume boundary. It is superseded for the volume contract by `pattern-discovery1-r2-semantic-integrity-2026-09-10.md`; the original record is retained as history.

## 证据边界

- 当前 stable：`feature/research-system-v01@c4d7513a6313c5368b2f584a13ac1fbf70efdf5e`。
- Owner checkout 未用于执行；本轮使用独立 worktree `luna/pattern-discovery-v01`。
- Owner 机器的默认 `~/.vibe-research/research_data_plane` 当前没有 manifest / Parquet artifact，因此没有把本机真实研究数据写成已验证事实。
- 工程验证使用现有 `research_data_plane.import_csv` 导入的临时、确定性 CSV→Parquet artifact；测试结束后临时目录已清理。没有保存完整 provider 或 artifact payload。
- Pattern source 只有现有 RDP `code/trade_date/open/high/low/close/volume`；没有新增 provider、逐票 HTTP 请求、写入或投资 authority。

## 现有事件注册表与语义

读模型固定为五类现有技术事件：

| 读模型 event_type | 现有单票 trigger alias | 计算语义 |
| --- | --- | --- |
| `close_above_20d_high` | `close_above_20d_high` | 当前 close > 不含当前日的前 20 个 high 的最大值 |
| `close_below_20d_low` | `close_below_20d_low` | 当前 close < 不含当前日的前 20 个 low 的最小值 |
| `sma20_cross_above_sma60` | `sma_golden_cross` | prev SMA20 ≤ prev SMA60 且 current SMA20 > current SMA60 |
| `sma20_cross_below_sma60` | `sma_death_cross` | prev SMA20 ≥ prev SMA60 且 current SMA20 < current SMA60 |
| `volume_surge` | `volume_spike` | 历史记录中的 PR #303 drift：SMA(volume, 5) / SMA(volume, 20) ≥ 2.0；该边界已由 R2 恢复为严格 > 2.0 |

SMA 与量比 alias 保留在 event evidence 中，避免改动现有单票 API type 名称。原始记录把精确等于 2.0 写成事件语义，这一结论已被 R2 更正；当前合同见 R2 evidence。

没有加入 MACD/KDJ/RSI/BOLL、跳空、评分、预测、leader、BUY/SELL 或推荐语义。

## RDP set-based 结果

`backend/research_data_plane.py::query_patterns` 在一个 DuckDB 查询中读取现有 Parquet，按 code 计算窗口，再只对每个 code 的最新 artifact-scope row 做读模型 shaping。没有调用 `technical_indicators`、Screener per-stock evaluator、provider client 或 `/api/kline`。

工程 fixture 的脱敏证据（只记录 identity/count/日期级信息）：

- source scope：2026-01-01 至 2026-03-07，208 rows，4 codes。
- effective `as_of`：2026-03-07；source date 来自 artifact 内不晚于 requested cutoff 的最大 `trade_date`。
- 五类事件全部由 fixture 触发：总计 6 个 event，000001 同日保留 3 个不同 event，000002 保留 3 个不同 event。
- 000003 有完整历史但无事件，证明 false/no-trigger 与 NOT_EVALUABLE 不混同。
- 600519 只有 10 rows，5 个事件评估均为 `NOT_EVALUABLE / INSUFFICIENT_HISTORY`；overall status 为 `partial`。
- response 分页 `limit=1` 返回 1 event、`total_events=6`、`next_offset=1`；event filter `volume_surge` 返回 2 events。
- `formal_state_write.performed = false`。

## 单票与 set-based parity

同一 fixture 的 000001 / 000002 通过现有 `technical_indicators.compute_indicators` 计算，再把历史 alias 映射为上表五个读模型 event code。set-based event identity 集合按 `(code, trade_date, event_type)` 比较，结果完全相同；event evidence 同时保留各窗口的 current/previous 值与 comparison，不压缩同日多事件。

## as_of 与未来行

请求 `latest=false&as_of=2026-03-06` 时：

- effective `as_of` 为 2026-03-06；
- 2026-03-07 的 fixture 触发值未出现在事件集合；
- response 的 source scope 仍由 artifact 与 cutoff 共同确定，不读取 cutoff 之后的行。

## fail-closed 与不可评估

- 缺少 RDP manifest 时路由返回 `status=unavailable`、空 events，不回退逐票 HTTP。
- 合法 manifest 下临时 Parquet 增加一个重复 `(code, trade_date)` row，并同步 manifest count/hash 后，`raw_row_count != unique_observation_count`；路由返回 `status=unavailable`、空 events，并暴露固定 limitation `PATTERN_SOURCE_DUPLICATE_OR_INVALID_OBSERVATION_IDENTITY`。
- Pattern runtime 不按 `(trade_date, code)` 静默去重；合法同股票同日不同事件仍由事件 type 分开保留。
- 历史不足、窗口字段缺失、零量比基准分别进入 `NOT_EVALUABLE` reason code；NOT_EVALUABLE 不作为未触发，也不宣称完整可评估。

## 浏览器垂直验证

使用 regular Playwright（当前环境没有 Browser plugin）：临时 RDP importer artifact + real FastAPI + production Vite dist。

- Desktop viewport：1440×900。
- Narrow viewport：390×844。
- 正常 fixture：确认同级 `形态扫描` tab、6 events、000001 三条同日事件、600519 `INSUFFICIENT_HISTORY` 在 summary 区直接可见、historical `as_of` 不读未来行。
- duplicate identity fixture：确认 API/UI 为 unavailable、空结果链接、limitation 在 summary 区可见，不能显示为完整正常扫描。
- 页面无 `pageerror`、console error 或 document/body horizontal overflow。
- 未新增 UI CTA、推荐或写入入口；保留现有 StockData / Candidate research links。

## 变更后的验证入口

- Backend：`backend/tests/test_research_data_plane_patterns.py`、相关 technical indicator tests。
- Frontend：`frontend/tests/patternDiscovery.test.ts`、现有 Screener / Full Market tests。
- Browser：`frontend/tests/e2e/pattern-discovery.browser.mjs`。

本记录只作为本轮实现与验证坐标；GitHub PR、exact-head CI、merge parent、post-merge stable CI 和 #203/Notion closure 仍以 live GitHub 与最终交接证据为准。
