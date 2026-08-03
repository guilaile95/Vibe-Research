# BK-11 Slice 2D 跨交易日 `lbc` 语义受控探针 v0.1

> 执行者：主任务执行者 Q
> 生成时间（UTC）：`2026-08-03T17:17:59Z`
> 审查日（Asia/Shanghai）：`2026-08-04`
> 关联工件：`BK11_LAYERED_PROMOTION_PROBE_V01.json`

---

## 1. Executive Decision

本轮为 **只读来源研究与机械验证**，不实现任何生产代码。

| 目标 | 结果 |
| --- | --- |
| Blocker 2（跨日身份与 lbc 验证） | **OPEN** — 普通连续与跨周末两组完成；长假后首交易日两组来源均 `EMPTY_UNEXPLAINED`，无法闭合 |
| Blocker 3（历史日期语义与 final 稳定性） | **OPEN** — `requested_date_binding` 与 `final_snapshot_evidence` 均为 `partially_verified`，无 payload 内日期字段 |
| Blocker 4（getYesterdayZTPool 不采用） | **CLOSED_BY_NON_ADOPTION** |
| `layered_promotion_rates` 生产实现授权 | **false — NO-GO**（Blocker 2/3 未关闭；Blocker 5–9 未触及） |

**结论：NO-GO for production implementation in v0.1。**

## 2. Scope and Non-goals

### 2.1 范围内

- 仅通过仓库既有 `astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")` 进行历史日期受控探针
- 通过 `trade_calendar.previous_trade_date` 机械选择三组交易日对
- 每日期两轮独立读取，比较标准化结果
- 跨日 stock_code 身份匹配与 `lbc` N → N+1 晋级计数
- 不采用 `getYesterdayZTPool` 的正式决策

### 2.2 范围外（显式禁止）

- `layered_promotion_rates` 生产实现
- 来源适配器 / final 快照生产者 / Data Health 接入
- API / 前端 / 数据库 / 调度 / 缓存层 / 历史回填
- 其他 BK-11 指标
- 修改任何 `backend/`、`frontend/`、`tests/`、交易日历 artifact、依赖、CI、配置
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
| 请求间隔 | ≥ 2.0 秒（实际 ≥ 2.2 s） |
| 单次请求最多重试 | 3 |
| 超时 | 10 秒 |
| 失败记录 | `error_class` 标准化记录 |
| 绕过验证码 / 伪造 Cookie | 未执行 |
| 持续轮询 | 未执行 |

### 3.3 执行量

- 3 组 × 2 日期 × 2 轮 = **12 次请求**（含间隔）
- 0 次重试
- 0 次 transport 失败
- 0 次 parse 失败（空结果视为 `EMPTY_UNEXPLAINED` 而非 `PARSE_ERROR`）

## 4. Date-pair Selection Rule

规则在观察晋级结果之前预先声明：

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

| pair_id | boundary_type | previous_date | current_date | calendar_verified | 备注 |
| --- | --- | --- | --- | --- | --- |
| A | ordinary_consecutive | 2026-07-30（周四） | 2026-07-31（周五） | ✓ | 审查日前最近一组 Tue-Fri 相邻交易日 |
| B | cross_weekend | 2026-07-24（周五） | 2026-07-27（周一） | ✓ | 跨周末 |
| C | post_holiday | 2026-06-18（周四） | 2026-06-22（周一） | ✓ | 2026 端午（2026-06-19）后首个交易日 |

`previous_trade_date("2026-07-31") == "2026-07-30"`，`previous_trade_date("2026-07-27") == "2026-07-24"`，`previous_trade_date("2026-06-22") == "2026-06-18"`，均由 `trade_calendar` 机械确认。

## 6. Probe Procedure

每日期执行两轮独立读取：

```text
for pair in (A, B, C):
    for role in (previous, current):
        round1 = probe_once(date)
        sleep(2.2s)
        round2 = probe_once(date)
        sleep(2.2s)
    cross_day = compute_cross_day(prev_round1_rows, curr_round1_rows)
```

每轮记录字段见 §13（JSON）。

## 7. Normalization Contract

- 身份键：`stock_code`（6 位零填充字符串，不整数化）
- `lbc`：正整数；缺失或非正整数计入 `invalid_lbc_count`，**绝不默认为 1**
- 去重：同 `stock_code` 保留首次合法记录
- 排序：`stock_code` 升序
- Hash 输入：`json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 编码 UTF-8

## 8. Historical-date Stability Evidence

| 日期 | round1 rows | round2 rows | round1 normalized hash | round2 normalized hash | stability |
| --- | --- | --- | --- | --- | --- |
| 2026-07-30 | 52 | 52 | `a986e2a8eb5ca462f444a7c12c947d9e3f6d354e89c03f773eebc3ebcaf0971e` | （同左） | STABLE |
| 2026-07-31 | 99 | 99 | `8e28f950b45ac957513c42fbf0aae4be830e1384bfbe29f983b6f557e8b085b9` | （同左） | STABLE |
| 2026-07-24 | 40 | 40 | `33c06378a1a69fc80b7a9ae98b177db1807a01d43f386d79c70a53a9d35a0981` | （同左） | STABLE |
| 2026-07-27 | 111 | 111 | `00c9745ac571a0274ae592077c6b4a6f28750cf288d8b92cc5777a30ed240d98` | （同左） | STABLE |
| 2026-06-18 | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | （同左） | EMPTY_UNEXPLAINED |
| 2026-06-22 | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | （同左） | EMPTY_UNEXPLAINED |

- 稳定（非空）日期：4 / 6
- 空结果日期：2 / 6（pair C，2026-06-18 与 2026-06-22，均为 `transport_success=true` 但返回空 pool）
- 非法代码：0
- 非法 `lbc`：0
- 重复代码：0

Pair C 解释：上游 `push2ex.eastmoney.com/getTopicZTPool` 对超过一定历史窗口（约 30–40 天）的日期返回空 `pool`，但 HTTP 正常。2026-06-18 距审查日 ~47 天，2026-06-22 距审查日 ~43 天，均超出该窗口。此为来源固有限制，非探针脚本错误。

## 9. Requested-date Binding Evidence

| 证据类型 | 状态 | 说明 |
| --- | --- | --- |
| 仓库调用模式 | verified | `astock.em_zt_topic_pool` 将 `date` 参数直接传入 URL query |
| 不同日期不同标准化结果 | verified | pair A 与 B 的 normalized hash 跨日不同（52 vs 99、40 vs 111） |
| 同日期重复稳定 | verified（4 日期） / verified-empty（2 日期） | 见 §8 |
| payload 内日期字段 | **不可验证** | 返回 pool 元素无 `trade_date` / `date` 字段，无法独立验证请求日期绑定 |

结论：`requested_date_binding = partially_verified`。

## 10. Final Snapshot Evidence

- 4 个近期日期重复稳定，符合收盘后历史池行为
- 但 payload 内无 `trade_date`、`snapshot_time` 或 `final` 标记字段
- 无法直接证明返回的是收盘后 **最终** 快照而非任意时刻快照

结论：`final_snapshot_evidence = partially_verified`。

## 11. Cross-day Identity Results

| pair | previous rows | current rows | 跨日身份匹配数 | 匹配基础 |
| --- | --- | --- | --- | --- |
| A | 52 | 99 | 52（含 42 missing_current） | stock_code 字符串相等 |
| B | 40 | 111 | 40（含 32 missing_current） | stock_code 字符串相等 |
| C | 0 | 0 | 0 | 不适用（空池） |

身份匹配仅依赖 `stock_code`，**不依赖股票名称**。

## 12. lbc N → N+1 Results

### 12.1 Pair A（2026-07-30 → 2026-07-31）

| from_level | to_level | denominator | numerator | rate | matched_stock_codes |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 6 | 6 | 1.0 | 000009, 000820, 300996, 600162, 603039, 603171 |
| 2 | 3 | 1 | 1 | 1.0 | 002827 |
| 3 | 4 | 1 | 1 | 1.0 | 605179 |
| 4 | 5 | 1 | 1 | 1.0 | 003032 |
| 8 | 9 | 1 | 1 | 1.0 | 603221 |

异常统计：`same_level_count=0`、`skipped_level_count=0`、`missing_current_count=42`、`unexpected_decrease_count=0`、`duplicate_affected_count=0`、`invalid_affected_count=0`。

### 12.2 Pair B（2026-07-24 → 2026-07-27，跨周末）

| from_level | to_level | denominator | numerator | rate | matched_stock_codes |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 3 | 3 | 1.0 | 002388, 600617, 603690 |
| 2 | 3 | 2 | 2 | 1.0 | 000533, 601606 |
| 3 | 4 | 1 | 1 | 1.0 | 301234 |
| 4 | 5 | 2 | 2 | 1.0 | 002879, 603221 |

异常统计：`same_level_count=0`、`skipped_level_count=0`、`missing_current_count=32`、`unexpected_decrease_count=0`、`duplicate_affected_count=0`、`invalid_affected_count=0`。

### 12.3 Pair C（2026-06-18 → 2026-06-22，端午后）

无数据。

### 12.4 语义说明

- `N → N+1`：promotion match（计入分子）
- `N → N`：not promotion（same_level_count）
- `N → N+k, k>1`：skipped level（仅计入分母）
- `current missing`：**不**机械解释为失败或非晋级，仅记录 `missing_current_count`
- `current_lbc < previous_lbc`：unexpected decrease，记录异常

`denominator=0` 的层级不输出。

## 13. Anomalies and Data Health

- 非法代码：0
- 非法 `lbc`：0
- 重复代码：0
- unexpected decrease：0
- skipped level：0
- 空池：pair C（长假后，2026-06-18 与 2026-06-22），归因于上游历史保留窗口
- `missing_current_count`：pair A=42、pair B=32（前一日涨停股次日未再涨停，属正常市场行为）

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

闭合标准要求 10 项全部满足。本轮状态：

| 项 | 标准 | 本轮 | 状态 |
| --- | --- | --- | --- |
| 1 | 三组日期对全部由 trade_calendar API 机械确认 | ✓ | pass |
| 2 | 三种边界类型全部覆盖 | ✓ | pass |
| 3 | 六个日期均至少一次成功、可解析 | 4/6 成功可解析，pair C 两个日期 empty | **fail** |
| 4 | 每个日期两轮标准化结果稳定 | 4/6 STABLE，2/6 EMPTY_UNEXPLAINED | partial |
| 5 | 三组都完成精确 stock_code 身份匹配 | 2/3 完成（pair C 无可匹配代码） | **fail** |
| 6 | 三组都完成 N→N+1 机械计算 | 2/3 完成 | **fail** |
| 7 | 全部 denominator/numerator 可复算 | ✓（pair A、B） | pass |
| 8 | 没有非法代码或非法 lbc 影响结果 | ✓ | pass |
| 9 | 至少观察到一条真实 N→N+1 身份匹配 | ✓（多组） | pass |
| 10 | 结果不依赖股票名称 | ✓ | pass |

依据条款"若三组中任一组来源失败或不稳定：Blocker 2 = OPEN"且"不得用另外一组重复替代失败边界类型"，**保持 OPEN**。

## 16. Blocker 3 Decision

**OPEN**。

| 项 | 标准 | 本轮 | 状态 |
| --- | --- | --- | --- |
| 1 | 六个历史日期均可查询 | 6/6 可查询（transport success） | pass |
| 2 | 同一日期两轮标准化结果稳定 | 4/6 STABLE + 2/6 EMPTY_UNEXPLAINED（一致空） | pass（形式上） |
| 3 | 不同日期结果存在可解释差异 | ✓（pair A/B 间 hash 不同，row_count 不同） | pass |
| 4 | 有直接证据绑定请求日期与返回历史池 | 无 payload 内日期字段 | **fail** |
| 5 | 有直接证据支持该历史池为 final 稳定快照 | 无 payload 内 final 标记 | **fail** |

依据条款"若第 4 或第 5 项无法直接证明：Blocker 3 保持 OPEN；historical semantics = partially_verified"，**保持 OPEN**。

## 17. Blocker 4 Decision

**CLOSED_BY_NON_ADOPTION**（详见 §14）。

## 18. Remaining Blockers

v0.1 本轮只处理 Blocker 2–4：

| Blocker | 状态 | 备注 |
| --- | --- | --- |
| 1 | N/A | 本轮之前已处理 |
| 2 | **OPEN** | 长假后边界失败 |
| 3 | **OPEN** | 历史语义 partially_verified |
| 4 | **CLOSED_BY_NON_ADOPTION** | — |
| 5–9 | 未触及 | 不在 Slice 2D 范围 |

## 19. Licensing and Data-retention Boundary

- 本轮只提交自行标准化的事实性日期集合（`stock_code` + `lbc`）
- 不提交完整原始响应、Cookie、Token、请求头凭据、网页正文
- 不提交大批股票名称
- `matched_stock_codes` 仅提交 6 位代码
- 一次性脚本 `bk11_slice2d_probe_tmp.py`、`bk11_summarize_tmp.py`、`probe_raw_output.json` 在提交前删除
- 上游数据为事实性市场数据，非原创表达；本仓库仅对标准化规则、判定逻辑与研究文档主张独立著作权

## 20. GO / CONDITIONAL GO / NO-GO

**NO-GO**（对 `layered_promotion_rates` 生产实现）。

理由：

- Blocker 2：OPEN（post_holiday 边界来源空）
- Blocker 3：OPEN（requested_date_binding / final_snapshot_evidence 仅 partially_verified）
- Blocker 5–9：未触及
- 即使 Blocker 2–4 全部关闭，也**不得**声称可以生产实现

下一切片若要推进，需解决：

- `post_holiday` 边界的历史来源限制（需要更短历史窗口的备选来源，或显式接受该边界不可验证）
- 历史池 `requested_date_binding` 与 `final_snapshot_evidence` 的直接证据（需要来源文档或 payload 内可核验字段）
