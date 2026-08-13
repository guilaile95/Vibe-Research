# Current Market Overview Runtime v0.1（P0-MO1）

> 回答 P0 用户第一层问题："现在 A 股整体市场环境怎么样？"——确定性、可审计、
> 诚实降级的市场上下文 read model。

## 文件

- `backend/market_overview_runtime.py`：纯组合层（新增，唯一生产 core）
- `backend/market_overview_runtime_router.py`：只读 endpoint（`GET /api/market/overview/facts`）
- `backend/app.py`：+2 行挂载（import + endpoint，独立于 D SEC2 的 LLM CLI 门区域）
- `backend/tests/test_market_overview_runtime.py`：25 tests（targeted + adversarial）
- `docs/p0/MARKET_OVERVIEW_RUNTIME_V01.md`：本文件

## Authority 声明

```text
MARKET_OVERVIEW_ROLE = MARKET_CONTEXT_READ_MODEL
INVESTMENT_ACTION_AUTHORITY = NO
HARD_RISK_AUTHORITY = NO
MATERIAL_CHANGE_AUTHORITY = NO
PORTFOLIO_EXPOSURE_AUTHORITY = NO
AI = NO
STALE_SNAPSHOT_CAN_LOOK_CURRENT = NO
```

## 复用（Anti-Rewheel）

| 能力 | 复用来源（stable authority） |
|---|---|
| breadth / limit activity / session / freshness / data health 数值 | `short_term_market_facts.compute_short_term_market_facts(snapshot)`（纯 producer，零 I/O，fail-closed） |
| 生产 snapshot | `fetch_final_limit_up_pool_snapshot(trade_date)`（T+1 可信 final） |
| breadth_state 描述 label | `market.py:_breadth_label` 阈值规则（冰点/偏弱/中性/偏强/普涨；中性/偏强含上界） |
| speculation_activity 描述 label | `market.py:_speculation_label` 阈值规则（冰点/普通/活跃/亢奋；>= 上界） |

**不重算任何市场事实**：runtime 只做 facts envelope → Overview 的规范化投影 + 机械 label 分档。

## 输出结构

```text
schema_version, facts_schema_version
trade_date, session, is_final, snapshot_at, fetched_at, source_ids
temporal_state = UNAVAILABLE | INTRADAY | AFTER_CLOSE_FINAL | UNKNOWN
breadth = { advance_count, decline_count, flat_count, suspended_count,
            valid_count, up_ratio, breadth_state }
limit_activity = { limit_up_count, limit_down_count, failed_limit_up_count,
                   touched_limit_up_count, sealed_limit_up_count,
                   failed_board_rate, seal_rate, speculation_activity }
data_state = AVAILABLE | PARTIAL | UNAVAILABLE
status, reason_codes, warnings, limitations, data_health
```

## 诚实纪律

- **freshness 保留**：trade_date / session / is_final / snapshot_at / fetched_at 全保留；
  旧快照绝不静默伪装 current（temporal_state 由 session/is_final 派生，非墙钟）。
- **0 ≠ unavailable**：producer unavailable 时 facts 数值为 None（未知），
  `0 limit_up` 与 `limit_up data unavailable` 严格区分。
- **partial ≠ complete**：status=partial → data_state=PARTIAL（不伪装 COMPLETE）。
- **unavailable 不伪造**：provider/日历失败 → data_state=UNAVAILABLE（绝不 fake neutral market）。
- **不提供 trade_date → UNAVAILABLE**（不猜 today；retrieval time ≠ market fact time）。
- **label 是描述性 context**：涨停多≠牛市、炸板多≠SELL、情绪差≠REDUCE——
  Market Overview 不是 DECISION AUTHORITY；不输出 BUY/SELL/REDUCE/EXIT、
  不推断 market regime / risk appetite / exposure / NBA。

## 边界（OUT_OF_SCOPE）

个股 BUY/SELL、Campaign/Formal Decision、Sell Engine、Hard Risk、Material
Change（MCP1=HOLD）、Portfolio sizing、#116/#118/#119 integration、frontend
首页重构（FULL_P0_HOME_REDESIGN = OUT_OF_SCOPE）。
