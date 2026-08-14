# Critical Data — Financials Capability Adapter v0.1

## 定位

`cap.security.financials` 是第一个正式 financials runtime capability
adapter。它只回答一个问题：

> 对一个 Security + Campaign + as_of，在上游已显式给出所需 report_period
> 的前提下，当前 Fact Lake 中是否存在一条可被正式接受的 canonical
> financial indicator publication？

它**不**回答：

- “当前应该看哪个 report period”（REPORT_PERIOD_SELECTION_AUTHORITY =
  UPSTREAM_EXPLICIT_ONLY；CDA1B_SELECTS_REPORT_PERIOD = NO）
- “这是当前最新财务报告”（LOCAL_LATEST_FINANCIAL_AUTHORITY = NO；
  PROVIDER_REVISION_ORDER_AUTHORITY = NO）
- PIT 重建（PIT_FINANCIAL_AUTHORITY = NO；POINT_IN_TIME_CLAIM = NO）
- 财务分析 / 评分 / 估值 / 盈利质量（FINANCIAL_ANALYTICAL_COMPLETENESS_AUTHORITY = NO）

## 评估链（全部只读、零写入）

```text
report_period_state / report_period / upstream authority refs
  → SER1 exchange routing（SSE → .SH，SZSE → .SZ；BSE NOT_PROVEN_V01）
  → Q1 canonical publication selection
       ├─ 无 pin：exact coordinate 下必须恰一条 COMMITTED
       └─ 有 pin：PUBLICATION_ID 精确选择（不存在 → NOT_EVALUATED，无 fallback）
  → FETCH receipt visibility gate（observation.fetched_at <= as_of）
  → verify_financial_normalization_replay（MATCH 才继续）
  → H2 collect + H1 assess（replay 维度由 adapter 的 dataset-specific
    authority 回填 MATCH；canonical_admissibility == USABLE 才继续）
  → query_financial_indicators(selection="publication", as_of=None)
  → payload 契约 + versions metric presence（至少一个 canonical metric）
```

## 冻结语义

```text
NAKED_REPORT_PERIOD_PROVES_APPLICABILITY = NO
FETCH_RECEIPT_VISIBILITY_GATE = YES
MULTIPLE_FINANCIAL_PUBLICATIONS_WITHOUT_PIN = NOT_EVALUATED
INTRA_PUBLICATION_REVISION_WINNER = NONE
MINIMUM_METRIC_PRESENCE = AT_LEAST_ONE_CANONICAL_METRIC
FACT_LAKE_READONLY = YES
```

禁止：

- `query_financial_indicators(selection="latest")` 作为 formal authority；
- `max(vintage_sequence)` / `highest update_flag` / `highest ann_date`
  → revision winner；
- 任何 BSE 六位代码 → `.BJ` 的算术变换或后缀猜测；
- 扫描所有 report_period 后自行选择；
- 本地最新 publication → 最新财务报告；
- provider / network 调用；Fact Lake 写入。

## 输出

```json
{
  "dependency_id": "cap.security.financials",
  "state": "USABLE | UNKNOWN | NOT_EVALUATED | ERROR",
  "security_code": "600519",
  "campaign_id": "campaign_...",
  "as_of": "...",
  "report_period_state": "RESOLVED",
  "report_period": "2026-03-31",
  "publication_id": "...",
  "source_observation_id": "...",
  "authority_refs": [],
  "reason_codes": [],
  "explainability": {}
}
```

仅 `USABLE` 时 `publication_id` / `source_observation_id` 非空。
`to_ccd_dependency_result()` 提供 CCD1 接受的精确四字段转换。

## 状态映射

| 条件 | state |
|---|---|
| RESOLVED period + 单条健康 canonical publication + replay MATCH + receipt visible + metric 存在 | USABLE |
| report_period_state=UNKNOWN | UNKNOWN |
| 无 publication / 多 publication 无 pin / BSE / future receipt / 全 null metric / health warning | NOT_EVALUATED |
| 契约漂移 / replay mismatch / health BLOCKED / 数据损坏 | ERROR |

本版本不产生 `BLOCKED` / `STALE`（无已冻结 freshness SLA authority）。

## 与 DDA1 / CCD1

DDA1 的 `MEDIUM` required set 包含 `cap.security.financials`。adapter 输出经
`to_ccd_dependency_result()` 后可直接作为 CCD1 dependency result；CCD1 拒绝
额外字段，因此完整评估对象与 CCD 输入之间使用显式转换。

## 边界

- 不修改任何现有 production authority（shadow / lake / Q1 / H1 / H2 / SER1 /
  DDA1 / CCD1 / data_contracts）。
- 不接入 DI2 runtime（DI2_FINANCIALS_RUNTIME_INTEGRATION = OUT_OF_SCOPE；
  需要单独的 Financial Report-Period Applicability Authority）。
- 不新增 dataset / provider；不调用 `run_financial_indicator_shadow`。
