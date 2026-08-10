# HiThink LIVE_SMOKE v0.1-R1 —— 证据报告（DS-H1）

> 状态：**LIVE_VERIFIED**（2026-08-10：真实凭据执行，15/15 端点业务成功 code=0）。
> Provider response = Observation，不是 Canonical Fact；本报告不改变任何
> 生产路由，HiThink 不会自动成为 canonical source。

---

## 1. Source Verification（2026-08-10 独立核验，非依赖旧报告/记忆）

| 项 | 值 |
|---|---|
| Provider | HiThink（同花顺官方）A 股金融数据服务 |
| 官方仓库 | `https://github.com/HiThink-Tech/Financial-API` |
| 默认分支 | `main` |
| 核验 commit SHA | `f8cdea908469b1b3b8bfb88dbb4d4a3959b1905c`（2026-07-24，github API 核验） |
| License | **MIT**（SPDX: `MIT`；README 明确「本仓库采用 MIT License」） |
| 文档位置 | `README.md`、`docs/README.md`、`docs/api/README.md`（+ `endpoints-*.md`、`capability-map.md`）、机器可读契约 `https://fuyao.aicubes.cn/llms-full.txt` |
| API base | `https://fuyao.aicubes.cn`（所有公开数据端点均为 `GET`） |
| 认证 | 统一 API Key：header `X-api-key: <KEY>`；推荐用户级环境变量 `HITHINK_FINANCE_API_KEY`（key 创建于 `https://fuyao.aicubes.cn/admin/`） |
| 成功规则 | **HTTP 200 不代表业务成功**；必须同时 `envelope.code == 0` |
| 错误信封 | `{code, message, request_id, data}`；业务错误 `data = null` |
| 官方错误码 | 1001 missing param / 1002 invalid format / 1003 out of range / 1004 conflict / 2001 unauthenticated / 2003 invalid key / 3001 instrument not found / 3002 data not ready / 3004 unsupported / 4001 rate limited / 5001-5003 server |
| NULL 语义 | 官方：「`null` 表示未披露或上游无值，不得自动补零」 |

> 文档矛盾记录：`docs/api/README.md` 是**契约索引页**（只列 `/api/meta/tickers/search`
> 一个端点示例），具体端点需从 `docs/api/endpoints-*.md` 与 `llms-full.txt` 读取；
> `capability-map.md` 的「weekly/monthly」区间描述与 `endpoints-prices.md` 的
> 「仅支持 1d」存在出入 —— 以端点页 `interval=1d` 为准，weekly/monthly 未在
> 本 probe 验证，标 `UNKNOWN`。

---

## 2. LIVE_AUTH 状态

```
LIVE_AUTH = PASS（2026-08-10 真实凭据执行成功）
LIVE_SMOKE 时间：2026-08-10T04:33 UTC（fetched_at）
```

执行记录（命令未含凭据，凭据经环境变量注入）：

```bash
export HITHINK_FINANCE_API_KEY=<env>   # 不打印值
cd backend && python -m tools.hithink_live_probe run --output "$TEMP/hithink_obs.json"
pytest tests/live/test_hithink_live_smoke.py -m live -q   # 10 passed
```

---

## 3. Probe 端点矩阵（契约来源 = DOC_VERIFIED；live 状态见 §4 报告矩阵）

> 证据分类说明：本文档每项声明均标注来源 —— `DOC_VERIFIED`（官方文档核验）、
> `LIVE_VERIFIED`（2026-08-10 真实请求验证）、`UNKNOWN`（无法证实）。
> 端点/参数语义以官方 `docs/api/endpoints-*.md` 为准；live 实测不一致处
> 已按实测修正（见 §6）。

| dataset_id | endpoint | 官方契约摘要（DOC_VERIFIED） | 历史语义（文档证据） |
|---|---|---|---|
| A. symbol_search | `/api/meta/tickers/search` | `q` 搜索/消歧；`limit` | lookup，无时间序列 |
| B. snapshot_quote | `/api/a-share/prices/snapshot` | `thscodes` 批量（R1：双标的 `600519.SH,000001.SZ`）；显式取数 `timestamp=null`，分页模式为最新有效时间 | **snapshot_only** |
| C. historical_daily | `/api/a-share/prices/historical` | `thscode` 单只、`interval=1d`、`start/end` 毫秒（窗口≤10年）、`adjust=none/forward/backward`（默认 forward）；bar 含 `date_ms`/OHLC | **by_date**（R2：2 标的 × 2 时间窗 + adjust 三模式矩阵 + 窗口绑定闭合） |
| D. income_statement | `/api/a-share/financials/income-statements` | `thscode`、`period=annual/quarterly`、`limit`/`start+end`；`period_end_ms` + `report_date_ms` + `fiscal_year/fiscal_period` | **by_date**（按报告期多期序列） |
| E. index_constituents | `/api/a-share-index/constituents/ths-stock-list` | 板块/指数当前成分（live 实测：参数 `thscode` 需 `.TI/.SH` 后缀） | **snapshot_only**（无 as-of 参数，不得伪造历史成员） |
| F. limit_up_pool | `/api/a-share/special-data/limit-up-pool` | `date_ms`（Asia/Shanghai 00:00，默认今天）、分页 | **by_date**（R2：显式历史 `date_ms=2026-08-07` 交易日） |
| 辅助 | `/api/a-share/calendar/trading-days` | 近一年交易日序列 | by_date（滚动窗口） |
| 辅助 | `/api/a-share/valuations/snapshot` | PE/PB/PS/PCF 批量快照，保留 null/负值 | snapshot_only |
| R2 非交易日 | `/api/a-share/prices/historical` | `2026-08-08`（周六）单日窗口 | LIVE_VERIFIED：code=0 + 空 items + timestamp=null |

> F 选择理由：limit-up pool 提供最强的 temporal/provenance 证据 —— `date_ms`
> 参数显式支持按历史交易日取成员（membership temporal），且与项目既有涨停链
> （BK11）领域相关，作为 cross-source verifier 候选价值最高。

---

## 4. 报告矩阵（LIVE_VERIFIED：2026-08-10 真实请求，全部 code=0）

| dataset_id | endpoint | live result | identifiers | temporal evidence | history_mode | revision support | NULL semantics | provenance strength | candidate role | confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| symbol_search | /api/meta/tickers/search | **VERIFIED** | thscode/ticker(后缀) | lookup，无时序 | snapshot_only | NOT_EXPOSED | 业务错误 data=null | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| snapshot_quote | /api/a-share/prices/snapshot | **VERIFIED** | thscode/ticker | 双标的 item=2 | snapshot_only | NOT_EXPOSED | timestamp 可 null | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| historical_daily | /api/a-share/prices/historical | **VERIFIED** | 仅请求 thscode（bar 带 date_ms） | 2×2 矩阵 8~10 根/窗 | by_date | NOT_EXPOSED | 空窗返回空 items | LIVE_VERIFIED | CANDIDATE_HISTORICAL_BACKFILL | MEDIUM |
| income_statement | /api/a-share/financials/income-statements | **VERIFIED** | thscode/ticker | annual 2 期 | by_date | **UNKNOWN**（无 revision/vintage 标识） | null=未披露 | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| index_constituents | /api/a-share-index/constituents/ths-stock-list | **VERIFIED** | thscode/ticker/name | 沪深300 当前成分 count=300 | snapshot_only | NOT_EXPOSED | 按端点页 | LIVE_VERIFIED | OBSERVATION_ONLY | MEDIUM |
| limit_up_pool | /api/a-share/special-data/limit-up-pool | **VERIFIED** | thscode/ticker/name | 显式 date_ms=2026-08-07 → count=5 | by_date | NOT_EXPOSED | 按端点页 | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| trading_calendar | /api/a-share/calendar/trading-days | **VERIFIED** | 日期序列 | 近一年 242 交易日 | by_date | NOT_EXPOSED | — | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| valuation_snapshot | /api/a-share/valuations/snapshot | **VERIFIED** | thscode | 单标的 PE/PB/PS/PCF | snapshot_only | NOT_EXPOSED | 保留 null/负值 | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| limit_up_explicit_date | /api/a-share/special-data/limit-up-pool | **VERIFIED** | thscode/ticker/name | 显式 date_ms=2026-08-07(交易日) count=5 | by_date | NOT_EXPOSED | — | LIVE_VERIFIED | CANDIDATE_VERIFIER | MEDIUM |
| non_trading_day | /api/a-share/prices/historical | **VERIFIED** | 请求 thscode | 2026-08-08(周六) → code=0 **count=0 空 items** | by_date | NOT_EXPOSED | timestamp=null | LIVE_VERIFIED | OBSERVATION_ONLY | MEDIUM |
| adjust_none / forward / backward | /api/a-share/prices/historical | **VERIFIED** | 请求 thscode | 三模式各 8 根 K 线 | by_date | NOT_EXPOSED | — | LIVE_VERIFIED | CANDIDATE_HISTORICAL_BACKFILL | MEDIUM |

---

## 5. Temporal Evidence（DOC_VERIFIED / LIVE_VERIFIED / UNKNOWN 分类）

| 概念 | 端点 | 状态 | 证据 |
|---|---|---|---|
| trade_date | historical_daily | LIVE_VERIFIED | `date_ms` 毫秒；R2 已断言返回 date_ms ∈ 请求窗口 + 顺序确定（ASCENDING/DESCENDING） |
| report_period | income_statement | LIVE_VERIFIED | `period_end_ms` + `fiscal_year/fiscal_period` |
| published/公告时间 | income_statement | UNKNOWN | `report_date_ms` 存在但官方未明确声明为公告时间 → 不伪造为 published_at |
| fetched_at | probe 本地生成 | DOC_VERIFIED | 允许（其余时间戳一律不发明） |
| revision_id / data_version | 全部 | UNKNOWN | financials 无 is_old/revision/corrected 标识（LIVE 响应亦未暴露） |
| adjustment_semantics | historical_daily | LIVE_VERIFIED | `adjust=none/forward/backward` 三模式均返回 K 线（R1/R2 实测）；`adjust` 参数语义由端点页声明 |

---

## 6. Live 观察（2026-08-10 实测，全部 code=0）

| 探测 | 结果 |
|---|---|
| symbol_search `q=600519` | 1 条匹配 |
| snapshot `600519.SH,000001.SZ` | 双标的各 1 条（count=2） |
| historical 2×2 矩阵 | `600519` 7/1–7/10 → 8 根；6/1–6/12 → 10 根；`000001` 同窗 → 8/10 根 |
| adjust 三模式（600519, 7/1–7/10） | none/forward/backward 各 8 根 |
| income annual limit=2 | 2 期报告 |
| index_constituents `000300.SH` | 沪深300 成分 **300 条**（当前快照） |
| limit-up 显式 `date_ms=2026-08-07` | 5 条（历史交易日成员有效） |
| trading_calendar | 近一年 **242** 交易日 |
| valuation_snapshot | 单标的 PE/PB/PS/PCF |
| **non_trading_day 2026-08-08(周六)** | **code=0 + count=0 空 items + timestamp=null**（非业务错误，静默空窗） |

## 6.1 R2 Live Evidence 闭合（2026-08-10，全部 LIVE_VERIFIED）

- **SNAPSHOT_EXPECTED_IDENTITIES_PRESENT**：`600519.SH,000001.SZ` 请求 → 受限身份集
  `_identities` 同时包含两标的（不断言价格、不从 count 推断）。
- **HISTORICAL_ALL_DATES_IN_REQUEST_RANGE**：2 标的 × 2 时间窗全部返回 date_ms ∈
  请求 [start, end]（毫秒窗口逐值断言）。
- **HISTORICAL_ORDERING_VERIFIED**：每窗 date_ms 顺序为 ASCENDING 或 DESCENDING
  （确定性，已记录于 `_temporal_summary.ordering`）。
- **HISTORICAL_OHLC_TYPES_VERIFIED**：open/high/low/close 字段类型 ⊆ {float,int,null}。
- 观测表示有界：`_identities` ≤ 10、`date_ms_values` ≤ 200、OHLC 采样 ≤ 10 条 ——
  不持久化完整 raw payload。

## 7. 结论与边界

- **REVISION_SEMANTICS**：官方文档与 live 响应均未暴露可区分「原版 vs 更正版」
  的标识 → 保持 **UNKNOWN**，绝不推断。
- **SNAPSHOT_NO_FAKE_HISTORY**：index_constituents(300 条当前成分) / snapshot /
  valuations 为 current-only；未证实历史成员 → 不制造历史。
- **NON_TRADING_DAY 行为**：非交易日返回空 items（code=0），消费方需自行区分
  「空窗」vs「错误」—— 这是观测，不是 DS-A1 规范化规则。
- **NO_CANONICAL_SWITCH**：本 slice 不修改任何生产 provider / routing / data-health /
  scheduler；HiThink 不自动成为 canonical。
- **候选角色仅为建议矩阵**，由 DS-A1（C lane）最终定义项目 canonical 契约。

## 8. R1 Security Posture（凭据安全）

- key 只经环境变量注入（本会话经仓库外 TEMP 文件读入进程 env，**未打印/未落库/未进 git**）；
- key 只进 HTTP header `X-api-key`；源码 / fixture / docs / PR / commit /
  observation JSON / fingerprint / stdout / stderr / exception / logs 均不含 key；
- offline 测试证明：fingerprint 白名单 fail-closed、递归 secret 键清洗
  （任意深度）、观测结构无 key 字段；
- 该 key 曾在对话中出现 → 视为已暴露，建议尽快到 fuyao.aicubes.cn/admin 轮换。
