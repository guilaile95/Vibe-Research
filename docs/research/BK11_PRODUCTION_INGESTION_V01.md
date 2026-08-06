# BK-11 生产快照写入接入决策 v0.1

| 项 | 值 |
|----|-----|
| 阶段 | bk11-production-ingestion-v0.1 |
| 分支 | feat/bk11-production-ingestion-v0.1 |
| Base | 12593c340845a60b70c925bdceb7265b5710511d |
| 结果 | **BLOCKED（路径 C）** —— 生产写入未实现 |

## 一、决策

来源合同审计（`BK11_PRODUCTION_INPUT_AUDIT_V01.md`）判定路径 C：BLOCKED。

阻塞核心：

```text
1. suspended_count 无可信来源（clist/get 无停牌状态标记字段；
   "缺失 change_pct 即停牌"无上游合同或响应证据）；
2. breadth 源无日期字段、无历史日期参数，日期绑定无法从源响应验证；
3. 涨跌停 legal-zero 未证明（已批准 adapter legal_zero 恒 False），
   0 值交易日无法生产；
4. 全 A 快照全量采集在当前网络环境反复断连（22 页断连、恢复后再次
   断连），收盘捕获生产可靠性无法保证。
```

## 二、未实现内容（诚实声明）

```text
- 无 bk11_ingestion_service / bk11_ingestion_router / bk11_input_adapter /
  bk11_input_store；
- 无 capture / finalize / ingest 生产入口；
- 无暂存表（第二数据库、同库暂存表均未创建）；
- 无 POST API / CLI 写入入口；
- 无 live smoke（未达到执行条件：来源合同未通过）；
- 无调度、无回填、无 Slice 4、无 layered_promotion_rates；
- 未改动任何生产代码、测试或前端文案。
```

## 三、若未来选择路径 B 的设计要点（候选，不实现）

仅当用户决定来源策略并完成合同验证后，可考虑：

```text
T 日收盘后：capture（全 A 快照 + 三池计数 + facts_data_health → 暂存表）
T+1：finalize（fetch_final_limit_up_pool_snapshot(T) → compute_daily_facts
     → 质量单调写入 fact_snapshots）
暂存：同 short_term_facts.sqlite3 独立表、按 trade_date 唯一键、内容 hash
      去重、质量单调（normal 不被 partial 覆盖）
入口：显式 POST/CLI，GET 无副作用，无自动调度
```

以上设计不构成任何实现承诺，全部待用户决定。

## 四、测试与验证状态

本轮为审计文档交付（BLOCKED 结果），无新代码：

```text
文档变更：BK11_PRODUCTION_INPUT_AUDIT_V01.md（新增）、
          BK11_PRODUCTION_INGESTION_V01.md（新增）、
          EXECUTION_STATE.md（状态行）
回归：后端全量离线（基线 3381 passed）复跑、git diff --check
```

## 五、等待用户决定

需要用户决定的数据来源策略（详见审计文档第七节）：

```text
- suspended_count / eligible_count 的权威口径来源；
- breadth 显式日期绑定来源（官方历史行情或捕获时点绑定是否被接受）；
- legal-zero 的 0 值日处理策略；
- 是否接受新增官方数据源（Tier A）或付费数据。
```
