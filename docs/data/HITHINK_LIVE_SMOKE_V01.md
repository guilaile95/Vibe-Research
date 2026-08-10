# HiThink LIVE_SMOKE v0.1-R1 —— 证据报告（DS-H1）

> 状态：**BLOCKED_LIVE_AUTH**（2026-08-10：旋转后凭据未注入执行环境；
> chat 中复制的 key 按安全指令视为已暴露，不使用）。
> 本报告只记录已**独立核实**的官方来源事实与探测契约；任何 live 结果在未
> 实际成功请求前一律标注 `UNKNOWN` / `NOT_RUN`，不伪造 PASS。
> Provider response = Observation，不是 Canonical Fact；本报告不改变任何
> 生产路由，HiThink 不会自动成为 canonical source。
>
> R1：harness 已增强（嵌套 `item[]` 观测、递归 secret 清洗、双标的快照、
> 历史 2×2 矩阵、adjust 三模式矩阵、limit-up 显式历史 `date_ms`、非交易日
> 行为探测）——live 运行待凭据注入后执行。

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
HITHINK_FINANCE_API_KEY = ABSENT（2026-08-10 R1 现场核验：进程 env / User scope 均无）
```

→ 按工作单 §3：**DS_H1 = BLOCKED_LIVE_AUTH**。probe harness（R1 增强）与
offline 测试已完成，但**不得宣称 LIVE_SMOKE = PASS**。旋转后凭据注入环境后执行：

```bash
python -c "import os; print(bool(os.environ.get('HITHINK_FINANCE_API_KEY')))"  # 期望 True
cd backend && python -m tools.hithink_live_probe run --output <TEMP_PATH_OUTSIDE_REPO>
pytest tests/live/test_hithink_live_smoke.py -m live -q
```

---

## 3. Probe 端点矩阵（文档核验的契约；live 结果 = NOT_RUN）

| dataset_id | endpoint | 官方契约摘要 | 历史语义（文档证据） |
|---|---|---|---|
| A. symbol_search | `/api/meta/tickers/search` | `q` 搜索/消歧；`limit` | lookup，无时间序列 |
| B. snapshot_quote | `/api/a-share/prices/snapshot` | `thscodes` 批量（R1：双标的 `600519.SH,000001.SZ`）；显式取数 `timestamp=null`，分页模式为最新有效时间 | **snapshot_only** |
| C. historical_daily | `/api/a-share/prices/historical` | `thscode` 单只、`interval=1d`、`start/end` 毫秒（窗口≤10年）、`adjust=none/forward/backward`（默认 forward）；bar 含 `date_ms`/OHLC | **by_date**（R1：2 标的 × 2 时间窗 + adjust 三模式矩阵） |
| D. income_statement | `/api/a-share/financials/income-statements` | `thscode`、`period=annual/quarterly`、`limit`/`start+end`；`period_end_ms` + `report_date_ms` + `fiscal_year/fiscal_period` | **by_date**（按报告期多期序列） |
| E. index_constituents | `/api/a-share-index/constituents/ths-stock-list` | 板块/指数当前成分 | **snapshot_only**（无 as-of 参数，不得伪造历史成员） |
| F. limit_up_pool | `/api/a-share/special-data/limit-up-pool` | `date_ms`（Asia/Shanghai 00:00，默认今天）、分页 | **by_date**（R1：显式历史 `date_ms=2026-08-07` 交易日） |
| 辅助 | `/api/a-share/calendar/trading-days` | 近一年交易日序列 | by_date（滚动窗口） |
| 辅助 | `/api/a-share/valuations/snapshot` | PE/PB/PS/PCF 批量快照，保留 null/负值 | snapshot_only |
| R1 非交易日 | `/api/a-share/prices/historical` | `2026-08-08`（周六）单日窗口 | 行为待 live 记录（空 items / 业务错误 / 其他） |

> F 选择理由：limit-up pool 提供最强的 temporal/provenance 证据 —— `date_ms`
> 参数显式支持按历史交易日取成员（membership temporal），且与项目既有涨停链
> （BK11）领域相关，作为 cross-source verifier 候选价值最高。

---

## 4. 报告矩阵（live_result 未运行 = UNKNOWN，诚实标注）

| dataset_id | endpoint | live result | identifiers | temporal evidence | history_mode | revision support | NULL semantics | provenance strength | candidate role | confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| symbol_search | /api/meta/tickers/search | UNKNOWN | thscode/ticker(后缀) | lookup，无时序 | snapshot_only | NOT_EXPOSED | 业务错误 data=null | DOC_VERIFIED | CANDIDATE_VERIFIER | LOW |
| snapshot_quote | /api/a-share/prices/snapshot | UNKNOWN | thscode/ticker | timestamp=null(显式)/最新(分页) | snapshot_only | NOT_EXPOSED | timestamp 可 null | DOC_VERIFIED | CANDIDATE_VERIFIER | LOW |
| historical_daily | /api/a-share/prices/historical | UNKNOWN | 仅请求 thscode（bar 不带） | start/end ms + date_ms/bar | by_date | NOT_EXPOSED | 按端点页 | DOC_VERIFIED | CANDIDATE_HISTORICAL_BACKFILL | LOW |
| income_statement | /api/a-share/financials/income-statements | UNKNOWN | thscode/ticker | period_end_ms + report_date_ms | by_date | **UNKNOWN（无 revision/vintage 标识可证明）** | null=未披露不得补零 | DOC_VERIFIED | CANDIDATE_VERIFIER | LOW |
| index_constituents | /api/a-share-index/constituents/ths-stock-list | UNKNOWN | thscode/ticker | 仅 current，无 as-of | snapshot_only | NOT_EXPOSED | 按端点页 | DOC_VERIFIED | OBSERVATION_ONLY | LOW |
| limit_up_pool | /api/a-share/special-data/limit-up-pool | UNKNOWN | thscode/ticker/name | date_ms 支持历史交易日 | by_date | NOT_EXPOSED | 按端点页 | DOC_VERIFIED | CANDIDATE_VERIFIER | LOW |

---

## 5. Temporal Evidence（文档层面，未 live 验证）

| 概念 | 端点 | 文档证据 |
|---|---|---|
| trade_date | historical_daily | `date_ms`（毫秒）；交易日历端点提供序列 |
| report_period | income_statement | `period_end_ms` + `fiscal_year/fiscal_period` EXPLICIT |
| published/公告时间 | income_statement | `report_date_ms`（「报告日期毫秒」，未明确声明为公告时间 → 不伪造为 published_at） |
| fetched_at | probe 本地生成 | 允许（其余时间戳一律不发明） |
| revision_id / data_version | 全部 | **NOT_EXPOSED / UNKNOWN**（financials 无 is_old/revision/corrected 标识） |
| adjustment_semantics | historical_daily | EXPLICIT：`adjust=none/forward/backward`（默认 forward；未验证服务端实现） |

---

## 6. 结论与边界

- **REVISION_SEMANTICS**：官方文档未暴露任何可区分「2025 年报原版 vs 更正版」的
  标识 → 保持 **UNKNOWN**，绝不推断。
- **SNAPSHOT_NO_FAKE_HISTORY**：index_constituents / snapshot / valuations 为
  current-only；未证实历史成员 → 不制造历史。
- **NO_CANONICAL_SWITCH**：本 slice 不修改任何生产 provider / routing / data-health /
  scheduler；HiThink 不自动成为 canonical。
- **候选角色仅为建议矩阵**，由 DS-A1（C lane）最终定义项目 canonical 契约。

## 7. R1 Security Posture（凭据安全）

- chat 中复制的凭据按用户安全指令视为**已暴露**，本任务不使用、不持久化；
- 只接受环境变量 `HITHINK_FINANCE_API_KEY` 的旋转后凭据（当前执行环境未注入）；
- key 只进 HTTP header `X-api-key`；源码 / fixture / docs / PR / commit /
  observation JSON / fingerprint / stdout / stderr / exception / logs 均不含 key；
- offline 测试证明：fingerprint 白名单 fail-closed、递归 secret 键清洗
  （任意深度）、观测结构无 key 字段。
