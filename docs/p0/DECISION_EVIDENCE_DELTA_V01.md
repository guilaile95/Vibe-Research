# Decision Evidence Delta Projection Core v0.1（P0-EC1）

> 纯确定性 domain core：回答 Frozen Decision 之后的第一个事实问题——
> **系统到底获得了哪些"真正新的"证据**。只区分时间与 identity 关系，
> 不判断投资意义（MATERIAL/CRITICAL/REVIEW_REQUIRED/BUY/SELL 一律不输出）。

## 文件

- `backend/decision_evidence_delta_projection.py`：纯 core（新增，唯一生产文件）
- `backend/tests/test_decision_evidence_delta_projection.py`：31 tests
- 依赖：零 I/O；复用仓库既有权威 idiom（canonical UTC 6 位微秒、
  STRATEGIES=(SHORT,SWING,MEDIUM)、campaign_id 格式）——不 import I/O modules

## Authority

```text
AUTHORITY = DECISION_EVIDENCE_TEMPORAL_DELTA
MATERIALITY_AUTHORITY = NO
RETRIEVAL_TIME_USED_AS_FACT_TIME = NO
CAMPAIGN_ISOLATION = YES
```

## 核心铁律（修复真实错误）

```text
RETRIEVAL TIME != FACT / EVENT TIME
```

今天抓到两个月前已发生的公告，不能因 `retrieved_at = today` 被当成 decision 之后
的新证据。只有 `effective_at`（事实在市场/业务语义上何时生效）参与"是否发生在
decision boundary 之后"判断。严禁 `retrieved_at > boundary → NEW_AFTER_DECISION`
自动成立。

## 时间关系分类

| 分类 | 条件 |
|---|---|
| NEW_AFTER_DECISION | effective_at > decision_boundary_at |
| PREEXISTING_AT_DECISION | effective_at <= decision_boundary_at（即使 retrieved_at 晚于 decision —— 最重要场景） |
| UNKNOWN_TEMPORAL_RELATION | effective_at missing / unreliable / time_semantics=UNKNOWN（绝不按 retrieved_at 猜） |
| OUT_OF_SCOPE | evidence identity 不属于当前 Campaign context |

## Identity 模型（v0.1 仅两种 scope）

- `security` scope：scope_id == target security_code → 可进入 candidate set。
- `campaign` scope：scope_id == target campaign_id → 才进入；严禁跨 Campaign
  传播（即使 security_code/strategy 相同）。
- 未知 scope / scope_id missing → fail closed（绝不 unknown scope → security-wide 广播）。

## 输入 / 输出契约

输入（调用方显式传入；core 不读任何 store）：

```text
DecisionContext: security_code(6 位数字), strategy(SHORT/SWING/MEDIUM),
                 campaign_id(campaign_<32hex>), decision_id, decision_boundary_at(canonical UTC)
NormalizedEvidenceItem: evidence_id(32hex), scope_kind, scope_id,
                        effective_at, retrieved_at, time_semantics(AUTHORITATIVE/UNKNOWN),
                        authority_refs
```

输出（frozen；to_dict/from_dict 严格）：

```text
schema_version, security_code, strategy, campaign_id, decision_id, decision_boundary_at,
new_evidence / preexisting_evidence / unknown_temporal_evidence / out_of_scope_evidence（证据 id 列表，按 id 稳定排序）,
has_new_evidence（至少一条 effective_at 晚于 boundary 的 scope-valid evidence；≠ material_change）,
temporal_coverage_complete（全部 scope-valid candidate 有可靠 effective_at 可裁决；存在 UNKNOWN → false）
```

## Fail-closed 输入契约

以下必须 fail closed（UNKNOWN 是合法业务状态，不是 schema corruption）：

```text
duplicate evidence_id / invalid campaign identity / invalid strategy / invalid scope_kind
/ invalid timestamp / effective_at malformed / decision_boundary malformed
/ AUTHORITATIVE 语义缺 effective_at（不静默降级 UNKNOWN）/ UNKNOWN 语义携带 effective_at
```

## 纪律（Determinism / Mutation / 边界）

- same input → same output；输入零突变；输出 deep isolated（重复调用无共享嵌套状态）。
- 证据列表输入顺序不影响语义（稳定排序按 evidence_id，不赋予投资优先级）。
- 不读 Current Thesis / Thesis Delta / Frozen Decision DB（boundary 由上游提供）。
- 不判断 Hard Risk / Data Health（即使 evidence 内容看似严重；provider outage/stale
  不是 NEW_AFTER_DECISION evidence，除非调用方传入带明确 effective_at 的业务事实）。
- 无 DB / SQLite / filesystem / network / FastAPI / AI / scheduler / wall clock /
  provider / new persistence / new dataset。

## 明确边界（FUTURE / 其他 authority）

- MATERIAL/CRITICAL 判断 = 未来 Material Change authority（本 core 只提供真实 delta facts）。
- Thesis 状态解释（WEAKENED/DISPROVEN/INVALIDATED）= Thesis authority。
- Hard Risk 分类 = Hard Risk authority。
- 决策有效性 = Decision Validity（上游提供 boundary）。
