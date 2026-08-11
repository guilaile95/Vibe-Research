# Fact Lake Health → Legacy Data Health Semantic Projection Core v0.1（DS-L1-H3）

> 纯 projection core：冻结 Fact Lake 健康（H1 7 维 + canonical_admissibility）与既有
> Data Health 词汇（normal / partial / unavailable + is_stale / is_degraded /
> error_code）之间的语义兼容契约。零 I/O，不接运行时/API/UI（FUTURE / NOT AUTHORIZED）。

## 文件

- `backend/fact_lake_health_legacy_projection.py`：纯 core（新增，唯一生产文件）
- `backend/tests/test_fact_lake_health_legacy_projection.py`：47 tests（评估矩阵 A-N +
  失败矩阵 + parity + 严格输入/输出 + 源码纯净扫描）
- 依赖：`data_health_service`（legacy 词汇权威）+ `fact_lake_health`（H1 输入权威）+
  `fact_lake_health_adapter`（H2 失败输入权威）——均只 import，不修改

## 复用既有权威（§4/§23/§34，无重复实现）

- `data_health_service.VALID_STATUSES`：legacy status 唯一来源
- `data_health_service.ERROR_SUMMARIES` / `error_summary(code)`：legacy error code /
  summary 唯一来源（绝不手写 summary；parity 测试强制相等）
- `fact_lake_health.FactLakeHealthAssessment.from_dict`：评估输入唯一权威（§9 严格重建）
- `fact_lake_health_adapter.HealthEvidenceCollectionFailure.from_dict`：集合失败输入唯一权威

## 输出契约（§7/§31）

`FactLakeLegacyHealthProjection`（frozen dataclass，to_dict/from_dict 严格校验）：

- 标识：schema_version / dataset_id / canonical_key / publication_id
- legacy 视图：legacy_status / legacy_is_stale / legacy_is_degraded /
  legacy_error_code / legacy_error_summary
- 原 Fact Lake 证据（§25 必须存活）：fact_lake_canonical_admissibility /
  fact_lake_reason_codes + 全部 7 维原值
- 来源：source_kind（ASSESSMENT / COLLECTION_FAILURE）/ collection_failure_code /
  lossiness（EXACT / LOSSY）

不输出 source_id / module / display_name / blocks_advice / block_reason。

## 评估映射（§10-§19，canonical_admissibility 为 primary 兼容权威）

| H1 状态 | legacy |
|---|---|
| 干净 USABLE | normal / 不 stale / 不 degraded / 无 error（EXACT） |
| stale-only（USABLE_WITH_WARNING + 仅 TEMPORAL_VALUE_STALE warning） | normal / is_stale=True / SOURCE_STALE（EXACT） |
| 其他 warning（REPLAY_NOT_RUN / DEGRADED / UNKNOWN / RECON 警告 / ARTIFACT_UNVERIFIED） | partial / SOURCE_PARTIAL（默认） |
| semantic_quality=degraded | partial / is_degraded=True / SOURCE_DEGRADED（优先级 A > B > C） |
| BLOCKED / 硬失败维度地板（NOT_COMMITTED / CORRUPTED / MISMATCH / invalid） | unavailable |

- **硬失败地板**（§11）：即使声称 USABLE，维度硬失败 → 保守 unavailable；绝不静默
  信任内部不一致 assessment。
- **blocked error 优先级**（§18）：SOURCE_CORRUPTED > SOURCE_SCHEMA_INCOMPATIBLE >
  SOURCE_UNAVAILABLE（storage 损坏不降级为 generic unavailable；schema mismatch
  不误标 corruption；其他 blocker 不误标 corruption）。
- **stale 独立轴**（§12/§13）：STALE+其他 warning → is_stale 仍 True 但 error 按
  优先级取 degraded/partial；绝不过早扁平化为 generic partial。

## 集合失败映射（§20-§22）

| H2 code | legacy |
|---|---|
| FACT_LAKE_NOT_INITIALIZED | SOURCE_NOT_INITIALIZED |
| FACT_LAKE_SCHEMA_UNSUPPORTED | SOURCE_SCHEMA_INCOMPATIBLE |
| FACT_LAKE_CORRUPTED / FACT_LAKE_PATH_UNSAFE | SOURCE_CORRUPTED |
| FACT_LAKE_BUSY / PUBLICATION_NOT_VISIBLE / RECONCILIATION_AMBIGUOUS | SOURCE_UNAVAILABLE |
| BAD_ARGUMENT / INTERNAL | **不投影**（编程/调用方错误 ≠ 数据源健康）→ raise，无 projection |

绝不发明 SOURCE_TIMEOUT（本地只读收集无 provider/网络）。

## 纪律（§26-§30/§35）

- NO_ADVICE_GATE / NO_FRESHNESS_RECOMPUTATION / NO_RECON_RECOMPUTATION /
  NO_STORAGE_REPLAY_RECOMPUTATION：只投影 H1 结论，不读任何存储/记录/时钟。
- Determinism（§30）：reason 顺序不影响 legacy_status / is_stale / is_degraded /
  error_code / lossiness。
- 纯净化：无 sqlite3 / filesystem / network / env / clock / DuckDB / Parquet /
  provider；无 SOURCE_REGISTRY 修改 / 无 DataHealthRecord 创建 / 无 aggregate_health /
  无 event store / 无 router / 无 frontend。
- NO_ADVICE_GATE：绝不从 BLOCKED/unavailable/corruption/stale/mismatch 推断
  blocks_advice（portfolio_advice_gate 是独立业务权威）。

## 明确边界（FUTURE / NOT AUTHORIZED）

运行时 Fact Lake health source 注册、Data Health adapter 接入、API/frontend 接线、
event persistence、scheduler、advice gating、H1/H2 修改、migration——全部后续独立 slice。

## 测试矩阵

- 评估矩阵 A-N（§32）：clean→normal、stale-only→normal+stale、replay not run→partial、
  quality degraded→SOURCE_DEGRADED、freshness unknown→partial、recon mismatch→partial、
  STALE+REPLAY_NOT_RUN→partial+SOURCE_PARTIAL、STALE+DEGRADED→SOURCE_DEGRADED、
  storage corrupted→SOURCE_CORRUPTED、schema mismatch→SOURCE_SCHEMA_INCOMPATIBLE、
  replay mismatch→SOURCE_UNAVAILABLE、recon drift→SOURCE_UNAVAILABLE、
  USABLE 声称+CORRUPTED→unavailable 地板、reason 顺序无关。
- 集合失败矩阵（§33）：7 个可映射 + BAD_ARGUMENT/INTERNAL 拒绝。
- Legacy parity（§34）：所有输出 status/error_code/error_summary 对既有权威逐一断言。
- 严格输入/输出：未知 reason/枚举/schema 拒绝、summary 漂移拒绝、重复 reason 拒绝、
  round-trip 相等。
