# Fact Lake Health Read-Only Evidence Adapter v0.1（DS-L1-H2）

> 纯只读桥接层：把已验收的 Fact Lake v3（S2）公共只读 authority 桥接进已验收的
> Fact Lake Health Core（H1），回答「能否只用权威只读 Fact Lake API 评估一个
> 已提交 publication，且零存储变更、零虚构证据」。

```
FactLake committed public read APIs
        ↓
collect_fact_lake_health_evidence(...)
        ↓
FactLakeHealthEvidence
        ↓
assess_publication_health(...)（H1 语义权威，不重复实现）
        ↓
FactLakeHealthAssessment
```

## 文件

- `backend/fact_lake_health_adapter.py`：纯只读 adapter（新增，唯一生产文件）
- `backend/tests/test_fact_lake_health_adapter.py`：29 tests（§32 全 acceptance gates）
- 依赖：S2 `fact_lake_store.py` 公共 API + H1 `fact_lake_health.py`（均只 import，不修改）

## 集成

- S2_BASE = `30d67b17e2ee2db62e0cc6ea3f6b20e83070d62d`（新分支起点）
- H1_ACCEPTED_DEPENDENCY = `81143d7641b472af03cdbd89c78cfb239b4dd7d2`（ordinary merge commit）
- 分支：`feat/ds-l1-fact-lake-health-adapter-v0.1`；Draft PR base = `feat/ds-l1-financial-indicator-generalization-v0.1`

## 只读硬不变量

- 仅接受 `lake.readonly is True`；可写句柄 → `BAD_ARGUMENT` 失败。
- 生产代码零写入口；只读句柄上的写操作由 store 自身 `FactLakeReadOnlyError` 拒绝。
- 不 import SQLite；不直接查表；不解析 control DB；不重复 schema / path / blob
  hashing 权威（Fact Lake Store 拥有，本模块只消费其结果）。

## 双层公共 API（§21）

| API | 行为 |
|---|---|
| `collect_fact_lake_health_evidence(lake, dataset_spec, request)` | 只读收集 → `FactLakeHealthEvidence` 或抛 `HealthEvidenceCollectionError` |
| `assess_fact_lake_publication(lake, dataset_spec, request)` | 收集 + H1 `assess_publication_health` → `FactLakeHealthAssessment`（不重复 H1 推导） |
| `HealthCollectionRequest(publication_id, freshness=None, expected_primary_temporal_value=None)` | 显式参数契约；唯一必填 publication_id |
| `FreshnessRequest(semantics, reference_at=None)` | 显式新鲜度请求（无时钟推断） |
| `HealthEvidenceCollectionFailure(code, detail)` | 确定性失败结果（to_dict/from_dict 严格校验） |

## 集合失败模型（§9）

公共 getter fail-closed（NotInitialized / SchemaVersion / Busy / Path / Corrupted /
HashMismatch）统一映射为确定性 code；绝不把未知来源的损坏猜测成某健康维度：

| code | 来源 |
|---|---|
| `FACT_LAKE_NOT_INITIALIZED` | `FactLakeNotInitializedError` |
| `FACT_LAKE_SCHEMA_UNSUPPORTED` | `FactLakeSchemaVersionError` |
| `FACT_LAKE_BUSY` | `FactLakeBusyError` |
| `FACT_LAKE_PATH_UNSAFE` | `FactLakePathError` |
| `FACT_LAKE_CORRUPTED` | `FactLakeCorruptedError` / `FactLakeHashMismatchError` / 契约漂移 / 非 `sha256:` 前缀 |
| `PUBLICATION_NOT_VISIBLE` | committed-only 读取返回 None（含 staged/failed/aborted） |
| `RECONCILIATION_AMBIGUOUS` | ≥2 个不同语义的绑定对账结果（绝不 winner/latest 选择） |
| `BAD_ARGUMENT` | 可写句柄 / 参数契约违反 |
| `INTERNAL` | 兜底（不泄露内部细节） |

集合失败 → 无 `FactLakeHealthEvidence`、无伪造 assessment。

## 证据来源（§8：VERIFIED 仅经公共 authority）

- `commit_state = COMMITTED`：`get_canonical_publication` 只返回 committed。
- `source_observations_committed = True`：`get_observation` 只返回 committed 且已 verify blob。
- `raw_payload_integrity = VERIFIED`：`get_observation`（verify_blob=True）+ publication
  source observation 绑定校验通过。
- `artifact_integrity = VERIFIED`：`verify_canonical_artifact`（公共 authority）通过。
- `NORMALIZATION_BINDING_REUSED`：`get_normalization`（store 已校验 hash + source 绑定）
  + publication 与 normalization 的 canonical payload 绑定由 store 校验。
- `replay_state = NOT_RUN`：REPLAY_COLLECTION = NOT_RUN_BY_GENERIC_ADAPTER_V01
  （Fact Lake Store v3 无通用跨数据集 replay 公共权威；未来 replay-health 独立 slice）。

## Artifact SHA 格式桥接（§11）

Fact Lake 存储 `sha256:<64 hex>` → H1 期望 `64 lowercase hex`。桥接仅：
`regex ^sha256:[0-9a-f]{64}$` 严格匹配后去掉前缀。uppercase digest / 非前缀 /
非法长度 → 拒绝（`FACT_LAKE_CORRUPTED`），绝不静默接受。

## 通用 temporal（§12）

- `primary_temporal_field` / `primary_temporal_value` 直接读自
  `StoredCanonicalPublication`，经 `TemporalSemantics(...)` 转换；无 dataset 名 switch。
- 矩阵：ds_limit_up_pool → TRADE_DATE（report_period 保持 None）；
  ds_financial_indicator → REPORT_PERIOD（trade_date 保持 None）。

## 新鲜度（§17/§18/§19）

- Adapter 不选语义、不读时钟（无 now/today/mtime/序/vintage 推断）。
- 仅调用方显式提供 `FreshnessRequest` 时按精确语义采集：
  - `FETCHED_AT` → committed source `ProviderObservation.fetched_at`；
  - `EFFECTIVE_AT`/`PUBLISHED_AT`/`OBSERVED_AT` → `CanonicalFact` 同名字段；
  - `TRADE_DATE`/`REPORT_PERIOD` → fact 精确坐标（`reference_at` 置 None）。
- 无值 → 留空 → H1 保持 UNKNOWN；无 cross-semantic substitution。
- `expected_primary_temporal_value` 为调用方策略上下文，严格校验后原样传给 H1。

## 对账 harvest（§14/§15）

- 仅 `list_reconciliations(dataset_id=...)`；过滤 left/right ∈
  `fact.source_observation_ids`。
- 0 个 → `reconciliation_result = None`（H1 用 persisted status / verifier 策略）。
- 1 个唯一语义 → 提供给 H1。多个精确重复 → 确定性去重。
- ≥2 个不同语义 → `RECONCILIATION_AMBIGUOUS` fail closed（绝不 latest/winner 选择）。
- 冲突（bound result ≠ persisted）→ adapter 成功收集，drift 判定委托 H1
  （`RECONCILIATION_STATUS_DRIFT` → BLOCKED），绝不在 adapter 隐藏。

## Zero-mutation（§23）

测试对 tmp lake 做收集前后全树指纹（文件集/目录集/大小/mtime/hash）比对，
并断言无 `-wal`/`-shm`/`-journal`/`.tmp`/`.bak` sidecar。健康读取纯观测。

## Corruption fail-closed（§24，tmp lakes only）

- raw blob 翻转 → 公共 authority fail closed → adapter 失败（`FACT_LAKE_CORRUPTED`）
  → 无伪造证据 → 文件保持未修复。
- canonical artifact 翻转 → 同上。
- control DB 中 normalized payload 内容翻转（表行受 immutability trigger 保护，
  按字节定位内容翻转）→ 同上。

## 非提交不可见（§25）

只 stage 不 commit 的 publication → `PUBLICATION_NOT_VISIBLE`；无 direct-SQL
escape hatch；H2 不产出 NOT_COMMITTED assessment（store 故意隐藏非提交）。

## 明确边界（FUTURE / NOT AUTHORIZED）

- 不修改 data_health_service / adapters / router / event_store / SOURCE_REGISTRY / frontend；
  不添加 `source_id="fact_lake"`；不接入既有 Data Health UI/API。
- 不修改 fact_lake_store.py / data_contracts.py / fact_lake_health.py。
- 无 provider / 无 live network / 无凭证 / 无 Fact Lake 写 / 无 schema 变更 / 无 migration。
- 无 generic replay orchestrator / 无 dataset-specific replay switch table。

## 测试矩阵

- **ds_limit_up_pool**（TRADE_DATE）：收集、SHABridge、freshness（FETCHED_AT/TRADE_DATE）、
  recon 六态、zero-mutation、corruption。
- **ds_financial_indicator（synthetic）**（REPORT_PERIOD）：收集、REPORT_PERIOD freshness、
  trade_date 保持 None。
- **源码纯净扫描**：生产 adapter 源码不含 sqlite3 / INSERT / UPDATE / DELETE / PRAGMA /
  Fact Lake 写入口 / datetime.now / date.today / data_health_service / data_health_adapters。
