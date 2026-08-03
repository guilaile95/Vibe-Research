# BK-11 Slice 2D 跨交易日 `lbc` 语义受控探针 v0.1

> 执行者：主任务执行者 Q
> 生成时间（UTC）：见 `BK11_LAYERED_PROMOTION_PROBE_V01.json`
> 审查日（Asia/Shanghai）：`2026-08-04`
> 关联工件：`BK11_LAYERED_PROMOTION_PROBE_V01.json`

---

## 1. Executive Decision

本轮为 **只读来源研究与机械验证**，不实现任何生产代码。本轮在原 v0.1 探针基础上修正 denominator 公式、证据边界与离线可复算性。

| 目标 | 结果 |
| --- | --- |
| Blocker 2（跨日身份与 lbc 验证） | **OPEN** — Pair A、B 完成修正公式并机械可复算；Pair C 两个日期均 `EMPTY_UNEXPLAINED`，`cause = not_verified` |
| Blocker 3（历史日期语义与 final 稳定性） | **OPEN** — `requested_date_binding` 与 `final_snapshot_evidence` 均为 `partially_verified`，payload 内无可核验日期字段 |
| Blocker 4（getYesterdayZTPool 不采用） | **CLOSED_BY_NON_ADOPTION** |
| `layered_promotion_rates` 生产实现授权 | **false — NO-GO** |

**结论：NO-GO for production implementation in v0.1。**

## 2. Scope and Non-goals

### 2.1 范围内

- 仅通过仓库既有 `astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")` 进行历史日期受控探针
- 通过 `trade_calendar.previous_trade_date` 机械选择三组交易日对
- 每日期两轮独立读取，比较标准化结果
- 跨日 `stock_code` 身份匹配与 `lbc` N → N+1 晋级计数
- 提交最小标准化行，使独立审查者可离线复算 denominator / numerator / rate / anomaly 分类
- 修正 denominator 核心公式并降级不可验证的因果与许可声明

### 2.2 范围外（显式禁止）

- `layered_promotion_rates` 生产实现
- 来源适配器 / final 快照生产者 / Data Health 接入
- API / 前端 / 数据库 / 调度 / 缓存层 / 历史回填
- 其他 BK-11 指标
- 修改 `backend/`、`frontend/`、`tests/`、交易日历 artifact、依赖、CI、配置
- `getYesterdayZTPool` live 探针

## 3. Source and Request Discipline

### 3.1 来源

- 端点：`getTopicZTPool`
- URL：`https://push2ex.eastmoney.com/getTopicZTPool`
- 参数：`ut`、`dpt=wz.ztzt`、`Pageindex=0`、`pagesize=10000`、`sort=fbt:asc`、`date=YYYYMMDD`
- 请求头：`User-Agent`（默认 UA）+ `Referer: https://quote.eastmoney.com/`
- 响应解析：`(r.json().get("data") or {}).get("pool") or []`

### 3.2 请求纪律

| 项 | 值 |
| --- | --- |
| 串行化 | 严格串行，不并发 |
| 配置间隔 | probe implementation configured sleep 2.2 seconds between requests |
| 单次请求最多重试 | 3 |
| 超时 | 10 秒 |
| 失败记录 | `error_class` 标准化记录 |
| 绕过验证码或伪造访问凭据 | 未执行 |
| 持续轮询 | 未执行 |

提交 artifact 的秒级 UTC 时间戳未提供足够精度，因此精确最小 monotonic interval 不可由提交物独立验证。未观察到秒级时间戳违反 2 秒最低间隔。

### 3.3 执行量

- 首轮（2D 原始探针）：3 组 × 2 日期 × 2 轮 = **12 次请求**
- 修正轮（本轮）：Pair A + B 共 4 日期 × 2 轮 = **8 次请求**
- 0 次 transport 失败
- 0 次 parse 失败（Pair C 两个日期返回空 pool，归为 `EMPTY_UNEXPLAINED`）

## 4. Date-pair Selection Rule

规则为确定性规则；所选日期符合该规则；pre-observation timestamp 不可由提交物独立验证。

| pair_id | boundary_type | 选择规则 |
| --- | --- | --- |
| A | ordinary_consecutive | 审查日前最近一组星期二至星期五之间的相邻交易日 |
| B | cross_weekend | 审查日前最近一个星期一交易日及其 `previous_trade_date` |
| C | post_holiday | 2026 年审查日前最近一个长假后首个交易日及其 `previous_trade_date` |

约束：

- 所有日期必须 ∈ `trade_calendar.sessions`
- 所有日期 ≤ Asia/Shanghai 当前日期
- `previous_date == previous_trade_date(current_date)`

## 5. Selected Date Pairs

| pair_id | boundary_type | previous_date | current_date | calendar_verified |
| --- | --- | --- | --- | --- |
| A | ordinary_consecutive | 2026-07-30（周四） | 2026-07-31（周五） | ✓ |
| B | cross_weekend | 2026-07-24（周五） | 2026-07-27（周一） | ✓ |
| C | post_holiday | 2026-06-18（周四） | 2026-06-22（周一） | ✓ |

`previous_trade_date("2026-07-31") == "2026-07-30"`，`previous_trade_date("2026-07-27") == "2026-07-24"`，`previous_trade_date("2026-06-22") == "2026-06-18"`，均由 `trade_calendar` 机械确认。

## 6. Probe Procedure

每日期执行两轮独立读取：

```text
for pair in (A, B, C):
    for role in (previous, current):
        round1 = probe_once(date)
        sleep(>=2.2s)
        round2 = probe_once(date)
        sleep(>=2.2s)
    cross_day = compute_cross_day(prev_round1_rows, curr_round1_rows)
```

## 7. Normalization Contract

- 身份键：`stock_code`（6 位零填充字符串，不整数化）
- `lbc`：正整数；缺失或非正整数计入 `invalid_lbc_count`，**绝不默认为 1**
- 去重：同 `stock_code` 保留首次合法记录并计数
- 排序：`stock_code` 升序
- Hash 输入：`json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 编码 UTF-8

非身份字段（如价格、成交额、封单、行业）可能在不同日期重新读取时漂移；`normalized_rows` 才是本轮身份与 `lbc` 验证对象。

## 8. Historical-date Stability Evidence

| 日期 | round1 rows | round2 rows | round1 normalized_rows_sha256 | stability |
| --- | --- | --- | --- | --- |
| 2026-07-30 | 52 | 52 | `a986e2a8eb5ca462f444a7c12c947d9e3f6d354e89c03f773eebc3ebcaf0971e` | STABLE |
| 2026-07-31 | 99 | 99 | `8e28f950b45ac957513c42fbf0aae4be830e1384bfbe29f983b6f557e8b085b9` | STABLE |
| 2026-07-24 | 40 | 40 | `33c06378a1a69fc80b7a9ae98b177db1807a01d43f386d79c70a53a9d35a0981` | STABLE |
| 2026-07-27 | 111 | 111 | `00c9745ac571a0274ae592077c6b4a6f28750cf288d8b92cc5777a30ed240d98` | STABLE |
| 2026-06-18 | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | EMPTY_UNEXPLAINED |
| 2026-06-22 | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | EMPTY_UNEXPLAINED |

- 稳定（非空）日期：4 / 6
- 空结果日期：2 / 6（pair C；详见 §13）
- 非法代码：0
- 非法 `lbc`：0
- 重复代码：0

## 9. Requested-date Binding Evidence

| 证据类型 | 状态 | 说明 |
| --- | --- | --- |
| 仓库调用模式 | verified | `astock.em_zt_topic_pool` 将 `date` 参数直接传入 URL query |
| 不同日期不同标准化结果 | verified | pair A 与 B 的 normalized rows 跨日不同（52 vs 99、40 vs 111） |
| 同日期重复稳定 | verified（4 日期） / verified-empty（2 日期） | 见 §8 |
| payload 内日期字段 | **不可验证** | 返回 pool 元素无 `trade_date` / `date` 字段，无法独立验证请求日期绑定 |

结论：`requested_date_binding = partially_verified`。

## 10. Final Snapshot Evidence

- 4 个近期日期重复稳定，符合收盘后历史池行为
- 但 payload 内无 `trade_date`、`snapshot_time` 或 `final` 标记字段
- 无法直接证明返回的是收盘后 **最终** 快照而非任意时刻快照

结论：`final_snapshot_evidence = partially_verified`。

## 11. Cross-day Identity Results

| pair | previous_count | current_count | overlap_count | missing_current_count | promotion_count |
| --- | --- | --- | --- | --- | --- |
| A | 52 | 99 | 10 | 42 | 10 |
| B | 40 | 111 | 8 | 32 | 8 |
| C | 0 | 0 | 0 | 0 | 0 |

定义：

- `previous_count`：前一交易日标准化唯一合法行数
- `current_count`：当日标准化唯一合法行数
- `overlap_count`：previous 与 current 同时存在的 `stock_code` 数量
- `missing_current_count`：previous 存在、current 未观察到的 `stock_code` 数量
- `promotion_count`：overlap 中满足 `previous lbc N → current lbc N+1` 的股票数量

身份匹配仅依赖 `stock_code`，**不依赖股票名称**。

`missing_current` 的含义：current pool 未观察到该 `stock_code`。原因未分类，可能包括未进入当日涨停池或其他来源覆盖原因。在来源适配器与 Data Health 未实现前，不作进一步因果判断。

`missing_current` 不进入 numerator，但必须保留在 previous denominator。

## 12. lbc N → N+1 Results

### 12.1 公式合同（修正后）

```text
denominator_N =
    previous_normalized_rows 中 lbc == N 的全部唯一合法股票数量
    （包括 missing_current 代码；不依赖 current pool 是否存在）

numerator_N =
    上述 denominator 中，同一 stock_code 在 current_normalized_rows 存在，
    且 current_lbc == N + 1 的股票数量
```

`missing_current` 保留在 denominator，不进入 numerator，计入 `missing_current_count`，原因不分类。

每个 previous pool 中实际存在的 `lbc` 层都必须输出（`denominator > 0`，`numerator` 可以为 0，`rate` 可以为 0.0）。只有 `denominator == 0` 的层级不得输出。

不变量：

```text
sum(level.denominator) == previous_count
overlap_count == promotion_count + same_level_count + skipped_level_count + unexpected_decrease_count
previous_count == overlap_count + missing_current_count
matched_stock_codes 数量 == numerator
sample_count == denominator
rate == round(numerator / denominator, 4)
```

### 12.2 Pair A（2026-07-30 → 2026-07-31）

`previous_count = 52`，`current_count = 99`，`overlap_count = 10`，`missing_current_count = 42`，`promotion_count = 10`，`same_level_count = 0`，`skipped_level_count = 0`，`unexpected_decrease_count = 0`。

| from_level | to_level | denominator | numerator | rate | matched_stock_codes |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 42 | 6 | 0.1429 | 000009, 000820, 300996, 600162, 603039, 603171 |
| 2 | 3 | 6 | 1 | 0.1667 | 002827 |
| 3 | 4 | 1 | 1 | 1.0 | 605179 |
| 4 | 5 | 2 | 1 | 0.5 | 003032 |
| 8 | 9 | 1 | 1 | 1.0 | 603221 |

不变量验证：`sum(denom) = 42+6+1+2+1 = 52 == previous_count` ✓；`sum(numer) = 10 == promotion_count` ✓；`overlap_count = 10+0+0+0 = 10` ✓；`previous_count = 10+42 = 52` ✓。

### 12.3 Pair B（2026-07-24 → 2026-07-27，跨周末）

`previous_count = 40`，`current_count = 111`，`overlap_count = 8`，`missing_current_count = 32`，`promotion_count = 8`，`same_level_count = 0`，`skipped_level_count = 0`，`unexpected_decrease_count = 0`。

| from_level | to_level | denominator | numerator | rate | matched_stock_codes |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 23 | 3 | 0.1304 | 002388, 600617, 603690 |
| 2 | 3 | 13 | 2 | 0.1538 | 000533, 601606 |
| 3 | 4 | 2 | 1 | 0.5 | 301234 |
| 4 | 5 | 2 | 2 | 1.0 | 002879, 603221 |

不变量验证：`sum(denom) = 23+13+2+2 = 40 == previous_count` ✓；`sum(numer) = 8 == promotion_count` ✓；`overlap_count = 8+0+0+0 = 8` ✓；`previous_count = 8+32 = 40` ✓。

### 12.4 Pair C（2026-06-18 → 2026-06-22，端午后）

无数据。两个池均为空，无层级可输出。详见 §13。

### 12.5 语义说明

- `N → N+1`：promotion match（计入分子）
- `N → N`：not promotion（`same_level_count`）
- `N → N+k, k>1`：skipped level（计入分母但不计入分子；`skipped_level_count`）
- `current missing`：不机械解释为失败或非晋级；只记录 `missing_current_count`；保留在分母
- `current_lbc < previous_lbc`：unexpected decrease（`unexpected_decrease_count`）

## 13. Anomalies and Data Health

### 13.1 非法/重复/异常

- 非法代码：0
- 非法 `lbc`：0
- 重复代码：0
- unexpected decrease：0
- skipped level：0

### 13.2 Pair C 空结果诊断

`failure_observation`：2026-06-18 与 2026-06-22 在两轮请求中均返回空 pool，`transport_success=true`，`parse_success=true`。

`cause_status`：`not_verified`

`possible_explanations`（待验证假设，不作为结论）：

- `historical_retention_window_hypothesis`
- `upstream_empty_or_coverage_behavior`

`error_class`：`EMPTY_UNEXPLAINED`（保留）。

## 14. getYesterdayZTPool Non-adoption Decision

| 项 | 值 |
| --- | --- |
| 状态 | `NOT_ADOPTED_IN_V0_1` |
| 理由 1 | `getTopicZTPool(date)` 可显式指定 `previous_date`，语义明确 |
| 理由 2 | `getYesterdayZTPool` 的真实日期关系此前 `not_verified` |
| 理由 3 | 采用 `getYesterdayZTPool` 不会增加计算能力 |
| 理由 4 | 会引入额外隐式日期语义 |
| 本轮执行 | 未对 `getYesterdayZTPool` 执行任何 live 探针 |
| 未来重新采用条件 | 需重新验证其与 `getTopicZTPool(previous_trade_date(current_date))` 的等价关系 |

## 15. Blocker 2 Decision

**OPEN**。

| 项 | 标准 | 本轮 | 状态 |
| --- | --- | --- | --- |
| 1 | 三组日期对全部由 trade_calendar API 机械确认 | ✓ | pass |
| 2 | 三种边界类型全部覆盖 | ✓ | pass |
| 3 | 六个日期均至少一次成功、可解析、非空 | 4/6 非空，pair C 两个日期 empty | **fail** |
| 4 | 每个日期两轮标准化结果稳定 | 4/6 STABLE，2/6 EMPTY_UNEXPLAINED | partial |
| 5 | 三组都完成精确 stock_code 身份匹配 | 2/3 完成 | **fail** |
| 6 | 三组都完成 N→N+1 机械计算 | 2/3 完成 | **fail** |
| 7 | 全部 denominator/numerator 可复算 | ✓（pair A、B，由提交的 normalized rows 可独立复算） | pass |
| 8 | 没有非法代码或非法 lbc 影响结果 | ✓ | pass |
| 9 | 至少观察到一条真实 N→N+1 身份匹配 | ✓ | pass |
| 10 | 结果不依赖股票名称 | ✓ | pass |

依据条款"若三组中任一组来源失败或不稳定：Blocker 2 = OPEN"且"不得用另外一组重复替代失败边界类型"，**保持 OPEN**。Pair A、B 修正后的公式机械可复算，但不构成 Blocker 2 关闭。

## 16. Blocker 3 Decision

**OPEN**。

| 项 | 标准 | 本轮 | 状态 |
| --- | --- | --- | --- |
| 1 | 六个历史日期均可查询 | 6/6 可查询（transport success） | pass |
| 2 | 同一日期两轮标准化结果稳定 | 4/6 STABLE + 2/6 EMPTY_UNEXPLAINED（一致空） | pass |
| 3 | 不同日期结果存在可解释差异 | ✓（pair A/B 间 hash 不同，row_count 不同） | pass |
| 4 | 有直接证据绑定请求日期与返回历史池 | 无 payload 内日期字段 | **fail** |
| 5 | 有直接证据支持该历史池为 final 稳定快照 | 无 payload 内 final 标记 | **fail** |

依据条款"若第 4 或第 5 项无法直接证明：Blocker 3 保持 OPEN；historical semantics = partially_verified"，**保持 OPEN**。

不得把一致空结果视为历史稳定性已验证（pair C 两日期一致空不构成稳定性证明）。

## 17. Blocker 4 Decision

**CLOSED_BY_NON_ADOPTION**（详见 §14）。

## 18. Remaining Blockers

| Blocker | 状态 | 备注 |
| --- | --- | --- |
| 1 | CLOSED | 本轮不处理 |
| 2 | **OPEN** | post_holiday 边界空结果，cause not_verified |
| 3 | **OPEN** | 历史语义 partially_verified |
| 4 | **CLOSED_BY_NON_ADOPTION** | — |
| 5–9 | 未触及 | 不在 Slice 2D 范围 |

## 19. Licensing and Data-retention Boundary

本轮仅提交完成机械验证所必需的最小标准化字段：`stock_code` 与 `lbc`。

未提交完整原始 payload、股票名称或请求凭据。

本文件不作版权、原创性或再分发许可的法律结论。

## 20. Offline Reproducibility

离线复算输入 = `previous_normalized_rows` + `current_normalized_rows`（嵌入 JSON 每个 pair）。

独立审查者可仅凭提交物复算：

- 全部 `denominator`、`numerator`、`rate`
- `overlap_count`、`missing_current_count`
- `promotion_count`、`same_level_count`、`skipped_level_count`、`unexpected_decrease_count`
- `matched_stock_codes`

hash 只用于完整性对照（验证提交的 normalized rows 与原始探针产出一致），不替代可复算行数据。

`normalized_rows_sha256` 定义：仅 `stock_code+lbc` 标准化行，按 `stock_code` 升序确定性序列化后的 SHA-256。

`raw_pool_sha256` 定义：从响应 `data.pool` 提取后的原始 pool 数组，经过确定性 JSON 序列化后的 SHA-256。**不是**完整 HTTP 响应 hash。

## 21. GO / CONDITIONAL GO / NO-GO

**NO-GO**（对 `layered_promotion_rates` 生产实现）。

理由：

- Blocker 2：OPEN（post_holiday 边界空结果，cause not_verified）
- Blocker 3：OPEN（requested_date_binding / final_snapshot_evidence 仅 partially_verified）
- Blocker 5–9：未触及
- 即使 Blocker 2–4 全部关闭，也**不得**声称可以生产实现

下一切片若要推进，需解决：

- `post_holiday` 边界的空结果成因（需来源适配器 + Data Health 提供可验证证据）
- 历史池 `requested_date_binding` 与 `final_snapshot_evidence` 的直接证据
- Blocker 5–9（未在本轮授权范围）
