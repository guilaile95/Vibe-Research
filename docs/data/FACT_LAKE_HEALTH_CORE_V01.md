# Fact Lake Dataset Health & Canonical Admissibility Core v0.1（DS-L1-H1）

> 纯确定性 domain core：给定 `DatasetSpec`、`CanonicalFact` 与独立采集的
> Fact Lake 完整性/回放/对账证据，输出该 canonical publication 的 7 维健康
> 评估。零 I/O（无 DB / 文件 / 网络 / 时钟 / provider）；不接入现有 Data
> Health UI（FUTURE / NOT AUTHORIZED）。

## 文件

- `backend/fact_lake_health.py`：纯 core（新增，唯一生产文件）
- `backend/tests/test_fact_lake_health.py`：68 tests（41 原始 + 19 R1 + 8 R2；
  两矩阵 + 全 acceptance + 无阈值新鲜度 + persisted 对账可见性）

## 7 维健康（不塌缩为单一 boolean）

| 维度 | 值 |
|---|---|
| publication_visibility | COMMITTED / NOT_COMMITTED（仅 COMMITTED 可见，§9） |
| storage_integrity | VERIFIED / UNVERIFIED / CORRUPTED（artifact/raw hash 失败 → CORRUPTED，§17） |
| reproducibility | MATCH / NOT_RUN / UNSUPPORTED / MISMATCH（MISMATCH → BLOCKED；UNSUPPORTED ≠ corruption，§18） |
| semantic_quality | valid / degraded / unknown / invalid（复用 QualityStatus，绝不升级，§19） |
| freshness | CURRENT / STALE / UNKNOWN / NOT_APPLICABLE（仅显式权威 basis + 显式 reference + 显式 max_staleness 策略才可能 CURRENT/STALE；无阈值策略 → UNKNOWN，§12-16） |
| reconciliation | 复用 ReconciliationStatus + not_applicable/not_run（persisted 状态始终可见，不依赖 verifier 路由；无 verifier 不惩罚，§21-23） |
| canonical_admissibility | USABLE / USABLE_WITH_WARNING / BLOCKED（硬失败 → BLOCKED，§27） |

## 复用既有权威（无重复实现）

- `DatasetSpec`（fetch_semantics / history_mode / required_temporal_fields /
  point_in_time_supported / revision_semantics / adjustment_semantics /
  max_staleness_seconds / routes）—— `DatasetSpec.validate_fact()` 是 CanonicalFact 准入语义权威
- `CanonicalFact`（quality_status / reconciliation_status / temporal 字段 / provenance_chain）
- `ReconciliationResult` / `ReconciliationStatus` / `FetchSemantics` / `HistoryMode` /
  `TemporalSemantics` / `QualityStatus` / `RevisionSemantics`

## 关键纪律

- **NO_FAKE_FRESHNESS**：无显式 freshness_semantics → UNKNOWN；by_date 无 expected → UNKNOWN；
  max_staleness 仅显式 UTC basis 才应用；从不隐式用墙钟 / mtime / 文件名 / 序；
  无 max_staleness 策略时时间戳+reference 只证明 age，不判可接受性（→ UNKNOWN，不推断隐式阈值）。
- **NO_PIT / NO_AS_OF**：snapshot_only 不做历史回填；不实现 as_of / PIT。
- **NO_PROVIDER_SWITCH**：对账 MISMATCH 仅产生 warning，绝不切换 provider / 选择 winner。
- **LEGAL_ZERO**：空 payload 不是通用失败（dataset 专属 canonicalization 拥有该语义）。
- **RESTATABLE**：多 revision 合法非 corruption；不做 latest-row-wins；vintage_sequence 仅本地发布序。
- **通用 temporal**：REPORT_PERIOD 与 TRADE_DATE 均按 required_temporal_fields 通用处理，不硬编码 trade_date。

## 现有 Data Health 未来映射（FUTURE / NOT AUTHORIZED）

现有 `data_health_service` 三态（normal/partial/unavailable）+ source-specific stale 逻辑是请求级
健康；Fact Lake 健康先冻结多维语义，未来再由独立 adapter 把
`canonical_admissibility` 等映射进既有 UI 三态投影。H1 不加 `source_id="fact_lake"`、不改 SOURCE_REGISTRY。

## 测试矩阵

- **ds_limit_up_pool**（BY_DATE / TRADE_DATE / PIT=false）：TRADE_DATE 健康、无 PIT 推断、legal-zero 合法。
- **ds_financial_indicator（synthetic）**（BY_DATE / REPORT_PERIOD / RESTATABLE / PIT=false）：
  REPORT_PERIOD 通用、trade_date 非必需、多 revision 非 corruption、无 latest-wins、无伪造 published_at。
