# 投资逻辑与证据账本 — MVP 技术设计（草案 v3）

> 状态：**设计草案 v3，非最终定案**。所有字段、表结构和 API 路由均为候选提案，需通过审查后方可进入实现阶段。
> （2026-08-07 更新：Evidence Thesis 已实现并上线，本文件保留为历史设计稿）
>
> 基线：`feature/research-system-v01` @ `2aed400623072750dabac0d3f5849aaaf142ff58`
>
> 路线来源：`docs/research/product-roadmap-next-phase.md` §三（P0：投资逻辑与证据账本）

## 仓库状态约定

```text
稳定分支：feature/research-system-v01
稳定 SHA：2aed400623072750dabac0d3f5849aaaf142ff58
PR #17：已合并（前端 API 类型拆分）
PR #18：已合并（后端缓存与 lifespan 加固）
PR #19：已合并（下一阶段产品路线图）
PR #20：当前设计 Draft PR
```

## 一、设计目标

为每只股票、板块或主题维护一份持续更新的投资逻辑，使投资判断可追溯、可更新、可证伪。第一版只做**手工**创建、编辑、关联和版本化，不涉及自动抓取或 AI 自动修改。

核心原则（继承自路线图）：

1. 所有投资判断都应可追溯到具体证据和数据时间。
2. 事实、推断、未知项必须分开表达。
3. 系统只提供研究辅助，不自动下单。
4. 写入失败不破坏旧数据。
5. 删除操作有确认。

## 二、设计边界与约束

### 本设计阶段只产出文档

- 不写产品代码。
- 不修改现有持仓建议、投资政策、复盘或板块研究模块。
- 字段和表结构是**候选提案**，审查通过后才作为实现规格。

### 实现阶段将遵守的约束

- 独立 Draft PR，不与其他功能并行。
- 独立存储表，不修改现有 `portfolio.json`、`ai_generated_results`、`daily_review_snapshots` 等表。
- 独立 API 路由前缀，不污染现有端点。
- 不引入向量数据库、知识图谱或复杂全文搜索。
- 新功能路由不直接写入 `app.py`，使用独立 `evidence_thesis_router.py`，`app.py` 只做 `app.include_router(...)` 最小接入。
- 不引入新第三方依赖（包括 ULID 库）。

## 三、核心数据对象（候选字段）

以下字段为第一版候选最小集。字段名、类型和约束在实现前可调整。

### 3.1 EvidenceRecord

证据记录：一条可追溯的信息单元，关联到某个研究对象。

> **重要**：证据本身**不携带**立场（support/oppose/neutral）。立场属于"证据与投资逻辑的关联关系"，见 §3.4 `thesis_evidence_links.stance`。同一条证据可以分别以不同立场关联到不同的投资逻辑。

```text
id                  主键，全局唯一（uuid.uuid4().hex）
subject_type        研究对象类型：stock | sector | theme
subject_id          研究对象标识（股票规范化代码 / 板块 slug / 主题 slug）
evidence_type       证据类型：news | announcement | report | research_note | financial_filing | other
claim               证据核心主张（简短自然语言摘要，非原文复制）
source_title        来源标题
source_url          来源 URL（可选，本地文件类证据无 URL）
source_date         来源发布日期（ISO 8601 date；research_note/口头信息/无发布日期材料允许为空）
accessed_at         获取时间（ISO 8601 datetime，UTC，始终必填）
classification      分类：fact | inference | unknown
confidence          置信度：high | medium | low
created_at          记录创建时间（UTC ISO 8601）
updated_at          记录最后更新时间（UTC ISO 8601）
deleted             软删除标记：0=正常, 1=已删除（CHECK 约束）
deleted_at          软删除时间（可空）
```

**classification 语义**

- `fact`：可验证的客观事实（如"公司 Q3 营收同比增长 20%"）。
- `inference`：基于事实的推断（如"毛利率下降可能反映竞争加剧"）。
- `unknown`：信息不足或来源不可靠，暂无法分类。

### 3.2 InvestmentThesis

投资逻辑：针对某个研究对象的持续性研究结论，引用证据，有失效条件。

```text
id                      主键，全局唯一（uuid.uuid4().hex）
subject_type            研究对象类型（同 EvidenceRecord）
subject_id              研究对象标识（同 EvidenceRecord，规范化规则见 §5.9）
market                  市场标识：CN | HK | US | KR（仅 stock 类型由服务端解析，不由客户端填写）
title                   投资逻辑标题
summary                 投资逻辑摘要
status                  状态：active | weakened | invalidated | archived
core_claims             核心观点列表（JSON array of strings）
catalysts               催化因素列表（JSON array of strings）
risks                   主要风险列表（JSON array of strings）
invalidation_conditions 失效条件列表（JSON array of strings）
created_at              创建时间（UTC ISO 8601）
updated_at              最后更新时间（UTC ISO 8601）
current_revision        当前版本号（整数，从 1 开始；始终对应一条 thesis_revisions 行）
```

**status 语义**

- `active`：当前有效。
- `weakened`：部分失效条件已触发，但逻辑未完全推翻。
- `invalidated`：失效条件已满足，逻辑不再成立（保留历史，不删除）。
- `archived`：**冻结状态**。用户主动归档（如已清仓且不再跟踪）。归档后 `current_revision` 和对应 snapshot 成为冻结的最终聚合状态，不再因任何原因生成新 revision（详见 §5.11.7）。

### 3.3 ThesisRevision（聚合状态版本）

**ThesisRevision 记录的是 InvestmentThesis 聚合状态版本，不是只记录 thesis 文本字段的版本。**

聚合状态包含：

- thesis 主表字段（title、summary、status、core_claims、catalysts、risks、invalidation_conditions 等）；
- 当前有效证据关联（`thesis_evidence_links` 中未取消关联的行）；
- 每条关联的 stance；
- 当时 EvidenceRecord 的必要快照字段（见 §5.11.3 的最小字段集）。

```text
id                  主键，全局唯一（uuid.uuid4().hex）
thesis_id           关联的投资逻辑 ID
revision_number     版本号（从 1 递增）
snapshot            该版本的完整聚合状态快照（JSON，结构见 §5.11.3）
change_summary      变更摘要（用户填写；可提供默认值，但第一版不称为 AI 自动生成）
created_at          版本创建时间（UTC ISO 8601）
```

**不可变性**：ThesisRevision 记录一旦创建，不允许修改或删除（删除证据时也不删除历史版本，见 §5.12）。

**版本对应关系（核心不变量）**：

```text
investment_theses.current_revision
```

始终对应一条已经存在的、不可变的：

```text
thesis_revisions.revision_number
```

并且：

```text
GET /api/thesis/{id} 返回的当前聚合状态
≡ current_revision 对应的 ThesisRevision.snapshot
```

不存在"当前版本只在主表、版本表中缺失"的状态。

### 3.4 ThesisEvidenceLink（证据-投资逻辑关联）

```text
thesis_id           关联的投资逻辑 ID
evidence_id         关联的证据 ID
stance              立场：support | oppose | neutral（属于关联关系，不属于证据本身）
created_at          关联创建时间（UTC ISO 8601）
updated_at          关联最后更新时间（UTC ISO 8601，用于追踪 stance 修改）
PRIMARY KEY (thesis_id, evidence_id)
```

**stance 语义**

- `support`：该证据支持此投资逻辑。
- `oppose`：该证据反对此投资逻辑。
- `neutral`：该证据与此投资逻辑相关，但无明确方向。

**约束**：关联时 thesis 与 evidence 的 `(subject_type, subject_id)` 必须一致，防止把其他股票的证据误关联到当前股票逻辑（见 §5.16）。

## 四、第一版能力范围

### 4.1 第一版包含

1. 手工创建和编辑投资逻辑（InvestmentThesis）。
2. 手工添加证据（EvidenceRecord）。
3. 证据关联股票或板块（subject_type + subject_id）。
4. 证据以指定立场（stance）关联到某条投资逻辑；同一条证据可以不同立场关联不同逻辑。
5. **所有非归档 thesis 的聚合状态 mutation 都会生成新 revision**（创建、编辑、归档、关联、修改 stance、取消关联，以及因 EvidenceRecord 编辑/软删除触发的联动更新）。**archived thesis 冻结**，不再生成新 revision（详见 §5.11.7）。
6. 查看两个版本之间的字段级 diff（纯文本 + 数组差异，不支持 Markdown 富文本）。
7. 展示事实、推断和未知项（classification 字段）。
8. 数据全部本地存储（SQLite，不云端同步）。
9. 删除操作有确认（前端二次确认 + 后端软删除 + `deleted_at` 时间戳）。
10. 写入失败不破坏旧数据（事务回滚 + 原子写入）。
11. 所有 thesis 局部 mutation 支持乐观并发控制（`expected_revision`），防止丢失更新。

### 4.2 第一版暂不包含

- 自动抓取新闻并自动生成证据。
- AI 自动修改投资逻辑或自动生成 change_summary。
- 持仓建议自动引用证据。
- 自动交易或自动触发卖出。
- 复杂知识图谱、向量数据库或复杂全文搜索。
- 多用户权限或云端同步。
- 与 free-stockdb 集成。
- 跨模块引用每日复盘结论。
- `core_claims` 逐条关联证据（第一版只做 thesis-level 关联）。
- 行业（industry）分类（第一版只保留 stock/sector/theme，见 §5.9）。
- 多份历史备份（第一版只保留最近一份一致性备份，见 §5.13）。

## 五、技术决策（必须回答的 16 个问题）

### 5.1 使用 SQLite 还是独立 JSON 存储，为什么

**提案：SQLite。**

理由：

- 证据账本需要按 `subject_type`、`subject_id`、`classification`、`thesis_id` 等多维度查询，SQLite 的索引和 WHERE 过滤远优于 JSON 全量扫描。
- 版本快照（ThesisRevision）会随时间增长，JSON 文件全量读写成本线性上升；SQLite 按行存取更稳定。
- 需要事务保证（聚合状态 mutation + 生成版本快照必须原子完成），SQLite 原生支持事务，JSON 文件需要手动实现 tmp + rename。
- 项目已有成熟的 SQLite 存储模式（`ai_result_store.py`、`review_store.py`），复用一致性高。

JSON 仅用于 SQLite 行内的 `snapshot` 字段（存复杂嵌套结构），不作为顶层存储。

### 5.2 是否复用现有 SQLite 基础设施

**提案：复用模式，但不复用同一数据库文件。**

- **复用模式**：参照 `review_store.py` / `ai_result_store.py` 的"纯存储层"设计——显式接收 `db_path`、无 ORM、`CREATE TABLE IF NOT EXISTS`、CHECK 约束、损坏检测异常类、只读连接使用 `?mode=ro`。
- **独立数据库文件**：使用独立文件 `~/.vibe-research/evidence_thesis.db`（可用 `VR_DATA_DIR` 覆盖），不与 `ai_results.db` / `daily_review.db` 共享文件，避免跨模块迁移风险。
- **不修改现有表**：不触碰 `ai_generated_results`、`daily_review_snapshots`、`portfolio.json` 等现有存储。

### 5.3 数据表和索引

**候选表结构**：

```sql
-- schema 元信息
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 证据表
CREATE TABLE IF NOT EXISTS evidence_records (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('news','announcement','report','research_note','financial_filing','other')),
    claim TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_url TEXT,
    source_date TEXT,                       -- 允许为空（research_note/口头信息/无发布日期材料）
    accessed_at TEXT NOT NULL,              -- UTC ISO 8601，始终必填
    classification TEXT NOT NULL CHECK (classification IN ('fact','inference','unknown')),
    confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    deleted_at TEXT
);

-- 投资逻辑表
CREATE TABLE IF NOT EXISTS investment_theses (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    market TEXT CHECK (market IN ('CN','HK','US','KR') OR market IS NULL),  -- 仅 stock 由服务端解析写入
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','weakened','invalidated','archived')),
    core_claims TEXT NOT NULL,                  -- JSON array
    catalysts TEXT NOT NULL,                    -- JSON array
    risks TEXT NOT NULL,                        -- JSON array
    invalidation_conditions TEXT NOT NULL,      -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 1  -- 始终对应一条已存在的 thesis_revisions.revision_number
);

-- 投资逻辑版本表（不可变，记录聚合状态）
CREATE TABLE IF NOT EXISTS thesis_revisions (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    snapshot TEXT NOT NULL,                      -- 完整聚合状态快照（thesis 字段 + 当时所有关联证据的最小字段集）
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    UNIQUE (thesis_id, revision_number)
);

-- 证据-投资逻辑关联表（多对多：一条证据可关联多条逻辑，一条逻辑可引用多条证据）
CREATE TABLE IF NOT EXISTS thesis_evidence_links (
    thesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    stance TEXT NOT NULL CHECK (stance IN ('support','oppose','neutral')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thesis_id, evidence_id),
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
);
```

**候选索引（6 个额外索引）**：

```sql
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence_records(subject_type, subject_id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_evidence_classification ON evidence_records(classification) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_thesis_subject ON investment_theses(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_thesis_status ON investment_theses(status);
CREATE INDEX IF NOT EXISTS idx_revisions_thesis ON thesis_revisions(thesis_id, revision_number);
CREATE INDEX IF NOT EXISTS idx_links_evidence ON thesis_evidence_links(evidence_id);
```

> **注意**：不再单独为 `thesis_evidence_links(thesis_id)` 建索引——`PRIMARY KEY (thesis_id, evidence_id)` 已支持按 `thesis_id` 前缀查询。

**表与索引统计**：

```text
4 个领域表（evidence_records / investment_theses / thesis_revisions / thesis_evidence_links）
1 个 schema_meta 表
6 个额外索引
```

### 5.4 ID 生成规则

**提案：标准库 `uuid.uuid4().hex`。**

```python
import uuid
new_id = uuid.uuid4().hex  # 32 字符十六进制
```

理由：

- 已有 `created_at` 字段用于排序，不依赖 ID 实现时间排序。
- 避免新增 `ulid-py` 等第三方依赖。
- 避免手写 ULID 算法带来的实现风险。
- MVP 场景无中央分配需求，UUID v4 全局唯一即可。

### 5.5 Schema 版本

**提案：在数据库中维护 `schema_meta` 表。**

```sql
-- 初始化时写入
INSERT OR IGNORE INTO schema_meta(key, value)
VALUES ('schema_version', 'evidence_thesis_ledger_v1');
```

- 当前版本：`evidence_thesis_ledger_v1`。
- 后续升级时版本号递增（`v2`, `v3`...），迁移脚本按版本号分支执行。
- **打开数据库时先读 `schema_version`**：
  - 版本低于代码预期 → 执行前向迁移。
  - 版本高于代码版本 → **拒绝打开**（避免降级损坏）。
  - 版本匹配 → 正常使用。

### 5.6 原子写入和事务边界

**提案：SQLite WAL 模式 + 显式事务 + 每连接启用外键。**

**每连接 PRAGMA（合法 Python 示例）**：

```python
conn = sqlite3.connect(path, timeout=5)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA busy_timeout = 5000")

# 仅在可写初始化连接执行；journal_mode 设置会持久化
conn.execute("PRAGMA journal_mode = WAL")
```

**PRAGMA 适用范围**：

- `foreign_keys = ON`：**每个连接**执行（包括只读连接）。
- `busy_timeout = 5000`：**每个连接**执行（包括只读连接）。
- `journal_mode = WAL`：**仅可写初始化连接**执行一次（设置会持久化到数据库文件）。
- **只读连接不尝试修改 journal mode**，继续使用 `?mode=ro` 打开。

**只读连接示例**：

```python
uri = f"{Path(path).resolve().as_uri()}?mode=ro"
conn = sqlite3.connect(uri, timeout=5, uri=True)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")     # 只读连接也必须执行
conn.execute("PRAGMA busy_timeout = 5000")   # 只读连接也必须执行
# 不执行 PRAGMA journal_mode = WAL（只读连接不允许修改 journal mode）
```

**事务边界**：

- 每个写操作包裹在 `BEGIN IMMEDIATE ... COMMIT` 中。
- 所有 thesis 聚合状态 mutation 遵循 §5.11.4 的统一事务流程。
- **删除证据**：在同一事务内设置 `evidence_records.deleted=1` + 写入 `deleted_at` + 为所有关联 thesis 生成新 revision（见 §5.11.6）。
- **关联证据**：在同一事务内校验 `(subject_type, subject_id)` 一致 + 插入 `thesis_evidence_links` + 为 thesis 生成新 revision。
- 连接级别用 `threading.Lock` 保护（参照 `portfolio.py` 的 `_LOCK` 模式），避免 SQLite "database is locked"。
- 外键约束失败 → 返回明确的业务错误（不抛裸 SQL 错误）。
- 写入后不额外 `fsync`（SQLite 在 WAL 模式下自行管理持久化）。

### 5.7 API 路由

**候选路由**（全部在 `/api/thesis` 和 `/api/evidence` 前缀下；通过独立 `evidence_thesis_router.py` 暴露，`app.py` 仅 `app.include_router(...)`）：

```text
# 证据
GET    /api/evidence?subject_type=stock&subject_id=600519&limit=50&offset=0
POST   /api/evidence
GET    /api/evidence/{id}
PUT    /api/evidence/{id}                        # 联动更新所有关联 thesis 的 revision
DELETE /api/evidence/{id}?confirm=true           # 软删除 + 联动更新所有关联 thesis 的 revision

# 投资逻辑
GET    /api/thesis?subject_type=stock&subject_id=600519&limit=50&offset=0
POST   /api/thesis                                # 创建时同步生成 revision 1
GET    /api/thesis/{id}                           # 详情≡ current_revision snapshot；archived 时以 snapshot 为权威（详见 §5.11.8）
PUT    /api/thesis/{id}                           # 必须携带 expected_revision；archived 返回 409；否则生成新 revision
DELETE /api/thesis/{id}?confirm=true              # 归档：必须携带 expected_revision；生成新 revision（从此进入冻结状态）

# 投资逻辑版本
GET    /api/thesis/{id}/revisions                 # 列出所有版本（按 revision_number ASC）
GET    /api/thesis/{id}/revisions/{rev}           # 获取指定版本快照（含当时证据最小字段集）
GET    /api/thesis/{id}/diff?from=1&to=2          # 比较两个版本的字段级差异

# 证据关联（archived thesis 一律返回 409，详见 §5.11.8）
POST   /api/thesis/{id}/evidence                  # body: {evidence_id, stance, expected_revision, change_summary}
PUT    /api/thesis/{id}/evidence/{evidence_id}    # body: {stance, expected_revision, change_summary}
DELETE /api/thesis/{id}/evidence/{evidence_id}    # query: expected_revision + change_summary
```

**通用约束**：

- 所有列表接口必须支持分页：
  - `limit` 默认 50，最大 200。
  - `limit > 200` → 返回 **HTTP 422**。
  - `limit <= 0` → 返回 **HTTP 422**。
  - `offset` 默认 0。
  - `offset < 0` → 返回 **HTTP 422**。
  - **不静默截断**。
  - 默认排序：`updated_at DESC, id DESC`。
  - **revision 列表例外**：按 `revision_number ASC`。
- DELETE 操作必须带 `confirm=true` 查询参数，否则返回 400。`confirm=true` **只是防误调用机制**，不能替代权限校验或事务校验。
- 所有写操作返回最新数据快照（不返回裸状态码）。
- 错误用与现有端点一致的 `{detail: "..."}` 格式。
- 不接受客户端传入 `id`、`created_at`、`updated_at`、`deleted_at`、`current_revision`、`market`（服务端生成或解析）。

**乐观并发（thesis 局部 mutation）**：

以下接口必须支持 `expected_revision`：

```text
PUT    /api/thesis/{id}
DELETE /api/thesis/{id}
POST   /api/thesis/{id}/evidence
PUT    /api/thesis/{id}/evidence/{evidence_id}
DELETE /api/thesis/{id}/evidence/{evidence_id}
```

校验失败统一返回：

```text
HTTP 409
```

响应：

```json
{
  "detail": "投资逻辑已发生变化，请重新加载后重试",
  "current_revision": 4
}
```

**不得静默覆盖**。

> **EvidenceRecord 编辑和删除**不使用单个 thesis 的 `expected_revision`（一条证据可能关联多个 thesis），但必须通过单事务和写锁保证所有关联 thesis 的 revision 一致更新（见 §5.11.6）。

### 5.8 前端页面入口

**候选页面**：

```text
/thesis                   投资逻辑列表（可按研究对象过滤）
/thesis/new               新建投资逻辑
/thesis/:id               投资逻辑详情（含证据列表、版本历史、diff 视图）
/thesis/:id/revision/:rev 查看指定历史版本
/evidence                 证据库列表（可按研究对象、分类过滤）
/evidence/new             新建证据
/evidence/:id             证据详情与编辑
```

- 在主导航增加"投资逻辑"入口（与"持仓"、"复盘"并列）。
- 个股页（StockData）增加"投资逻辑"面板，按当前股票代码过滤展示。
- 路由懒加载（与现有板块研究页一致），不影响首屏体积。
- 不修改现有页面的核心逻辑，只在个股页新增一个可折叠面板。

### 5.9 研究对象的统一 subject 表达

**提案：`subject_type` + `subject_id` 二元组，第一版只保留 `stock | sector | theme`。**

| subject_type | subject_id 示例 | 说明 |
|---|---|---|
| `stock` | `600519` / `00700` / `AAPL` / `005930.KS` | 项目现有股票规范化代码（见 §5.9.1） |
| `sector` | `pcb` | 现有板块研究 workspace slug |
| `theme` | `ai_inference` | 自由主题 slug（用户自定义） |

**MVP 删除 `industry`**。理由：

- 当前没有独立的行业 slug 注册表；
- 同一对象可能被写成 `sector=semiconductor` / `industry=semiconductors` / `theme=semiconductor`，导致重复账本；
- 未来确有独立行业分类体系时，再通过 schema migration 增加 `industry` 类型，不在 MVP 预留重复类型。

**主题 slug 规范**：

- 小写；
- 仅允许字母、数字、短横线（`-`）或下划线（`_`）；
- 最大长度 64；
- 去除首尾空白；
- 不允许空字符串。

#### 5.9.1 股票标识必须覆盖项目现有市场

**不再使用只支持 A 股 6 位数字的新正则**。`subject_id` 必须使用项目现有股票输入的规范化标识：

| 市场 | 示例 subject_id | market（服务端解析） |
|---|---|---|
| A 股 | `600519` | `CN` |
| 港股 | `00700` | `HK` |
| 美股 | `AAPL` | `US` |
| 韩股 | `005930.KS` | `KR` |

**规范化规则**：

- 英文字母统一大写；
- 去除首尾空格；
- 后缀（如 `.KS`）统一大写；
- **不允许静默把韩股代码当作 A 股**（例如 `005930` 必须保留 `.KS` 后缀，不能截断为 6 位数字）；
- 使用项目现有股票代码识别逻辑（不重新定义只支持 A 股的正则）。

**market 字段**：

- 不由客户端自由填写；
- 由服务端解析 `subject_id` 后写入 `investment_theses.market`；
- 在快照和 API 返回中附加，便于前端按市场分组展示；
- `sector` 和 `theme` 类型的 `market` 为 `NULL`。

### 5.10 证据来源字段如何保持可追溯

**提案：必填字段 + 可选 URL + source_date 允许为空。**

| 字段 | 必填 | 说明 |
|---|---|---|
| `source_title` | 是 | 来源标题（用户录入，如"贵州茅台 2025 年三季报"） |
| `source_url` | 否 | 来源 URL（本地文件或口头信息可留空） |
| `source_date` | 否 | 来源发布日期（ISO 8601 date）；`research_note`、口头信息、无发布日期材料允许为空 |
| `accessed_at` | 是 | 用户获取该信息的时间（UTC ISO 8601，证明"何时看到"，即使 source_date 为空也始终必填） |

**约束**：

- `source_date` 有值时必须是有效 ISO 8601 date（`YYYY-MM-DD`）。
- `accessed_at` 始终必填，UTC ISO 8601 datetime。
- `source_date` 与 `accessed_at` 分开，避免把"旧新闻当新证据"。
- `claim` 字段存用户摘要（非原文复制），避免版权问题，同时保留可追溯的 `source_url`。
- 若来源是本地文件（如 PDF 研报），`source_url` 留空，`source_title` 写文件名。

### 5.11 版本变更如何生成

#### 5.11.1 ThesisRevision 是聚合状态版本

**ThesisRevision 记录的是 InvestmentThesis 聚合状态版本，不是只记录 thesis 文本字段的版本。**

聚合状态包含：

- thesis 主表字段（title、summary、status、core_claims、catalysts、risks、invalidation_conditions 等）；
- 当前有效证据关联（`thesis_evidence_links` 中未取消关联的行）；
- 每条关联的 stance；
- 当时 EvidenceRecord 的必要快照字段（见 §5.11.3）。

**核心不变量**：

```text
GET /api/thesis/{id} 返回的当前聚合状态
≡ current_revision 对应的 ThesisRevision.snapshot
```

#### 5.11.2 所有会产生 revision 的操作

以下操作都会创建新 revision：

| 操作 | 接口 | 是否需要 expected_revision | change_summary 来源 |
|---|---|---|---|
| 创建 thesis | `POST /api/thesis` | 否（新建） | 用户填写，默认"创建投资逻辑" |
| 编辑 thesis | `PUT /api/thesis/{id}` | 是 | 用户填写 |
| 归档 thesis | `DELETE /api/thesis/{id}?confirm=true` | 是 | 用户填写，默认"归档投资逻辑" |
| 关联证据 | `POST /api/thesis/{id}/evidence` | 是 | 用户填写 |
| 修改 stance | `PUT /api/thesis/{id}/evidence/{evidence_id}` | 是 | 用户填写 |
| 取消关联 | `DELETE /api/thesis/{id}/evidence/{evidence_id}` | 是 | 用户填写 |
| 编辑 evidence | `PUT /api/evidence/{id}` | 否（联动） | 固定建议"更新关联证据：{evidence_id}" |
| 软删除 evidence | `DELETE /api/evidence/{id}?confirm=true` | 否（联动） | 固定建议"删除关联证据：{evidence_id}" |

#### 5.11.3 历史 snapshot 必须保存当时的证据状态（最小字段集）

**问题**：仅在 snapshot 中保存 evidence ID 不够，因为 EvidenceRecord 后续可能被编辑、取消关联或软删除。历史版本将无法回答"当时引用了哪些证据？当时 claim 是什么？当时该证据是支持还是反对？"

**MVP 方案**：不新增 EvidenceRevision 表。在 `ThesisRevision.snapshot` 中嵌入不可变的证据快照数组。

**`snapshot.evidence_links[]` 必须至少包含以下字段（MVP 历史还原所需的最小字段集）**：

```text
evidence_id
evidence_type
stance
claim
classification
confidence
source_title
source_url
source_date
accessed_at
```

**snapshot 完整结构**：

```json
{
  "thesis": {
    "id": "...",
    "subject_type": "stock",
    "subject_id": "600519",
    "market": "CN",
    "title": "...",
    "summary": "...",
    "status": "active",
    "core_claims": ["..."],
    "catalysts": ["..."],
    "risks": ["..."],
    "invalidation_conditions": ["..."],
    "current_revision": 2,
    "created_at": "...",
    "updated_at": "..."
  },
  "evidence_links": [
    {
      "evidence_id": "...",
      "evidence_type": "announcement",
      "stance": "support",
      "claim": "...",
      "classification": "fact",
      "confidence": "high",
      "source_title": "...",
      "source_url": "...",
      "source_date": "...",
      "accessed_at": "..."
    }
  ]
}
```

**创建或更新 ThesisRevision 时**，把当时所有有效（未软删除、已关联）的证据的上述最小字段集复制进 snapshot。历史版本和 diff **只读取 snapshot**，不依赖当前 EvidenceRecord。

这样即使证据之后被编辑、被软删除、被取消关联，历史版本仍可完整还原。

#### 5.11.4 版本生成统一事务流程

**所有 thesis 聚合状态 mutation 统一遵循以下流程**：

1. 读取当前 thesis；
2. 校验 `expected_revision`（thesis 局部 mutation 必需）；
3. 执行业务修改；
4. 读取修改后的 thesis 主表字段；
5. 读取当前有效关联（`thesis_evidence_links`）；
6. 读取当前有效 EvidenceRecord（未软删除）；
7. 组装完整 snapshot（thesis 字段 + evidence_links 最小字段集）；
8. 插入新的 `ThesisRevision`（`revision_number = current_revision + 1`）；
9. 更新 `investment_theses.current_revision`；
10. 提交事务。

**任何一步失败**：

```text
ROLLBACK
```

旧状态和旧 revision 保持不变。

#### 5.11.5 创建投资逻辑

`POST /api/thesis`，同一事务内：

1. 创建 `investment_theses` 行，`current_revision = 1`。
2. 创建 `thesis_revisions` 行，`revision_number = 1`。
3. revision 1 的 `snapshot` 是创建后的完整聚合状态（创建时关联证据通常为空数组，`evidence_links: []`）。
4. `change_summary` 由用户填写，可提供默认值 `"创建投资逻辑"`。

#### 5.11.6 EvidenceRecord 修改的联动版本

一条证据可能关联多个 thesis。编辑或软删除 EvidenceRecord 时，必须在同一事务内为**所有非归档（status ∈ {active, weakened, invalidated}）的关联 thesis** 生成新 revision。**archived thesis 不联动**（见 §5.11.7）。

**编辑 EvidenceRecord（`PUT /api/evidence/{id}`）**，同一事务内：

1. 更新 `evidence_records` 行（刷新 `updated_at`）。
2. 查询所有仍关联该证据且 `status != 'archived'` 的 thesis。
3. 对每个 thesis 读取当前完整聚合状态。
4. 为每个 thesis 创建下一 revision（`revision_number = current_revision + 1`）。
5. 更新每个 thesis 的 `current_revision`。
6. 任一步失败则整体 `ROLLBACK`。

**固定 change_summary 建议**：

```text
更新关联证据：{evidence_id}
```

**软删除 EvidenceRecord（`DELETE /api/evidence/{id}?confirm=true`）**，同一事务内：

1. 设置 `evidence_records.deleted = 1`。
2. 写入 `evidence_records.deleted_at`。
3. 查询所有仍关联该证据且 `status != 'archived'` 的 thesis。
4. 为每个 thesis 创建下一 revision。
5. **新 snapshot 不再包含已删除证据**（`evidence_links` 数组中移除该 evidence_id）。
6. **旧 revision 继续保存删除前的证据快照**（不可变）。
7. 更新各 thesis 的 `current_revision`。
8. 任一步失败则整体 `ROLLBACK`。

**固定 change_summary 建议**：

```text
删除关联证据：{evidence_id}
```

> **联动范围一致性**：编辑和软删除使用**完全一致**的 thesis 查询范围（`status != 'archived'`）。archived thesis 既不联动编辑也不联动软删除。

> **注意**：EvidenceRecord 编辑和删除**不使用单个 thesis 的 `expected_revision`**（一条证据可能关联多个 thesis，无法让客户端同时为所有 thesis 提供一致的 expected_revision）。一致性由单事务 + 写锁保证。

#### 5.11.7 archived thesis 冻结语义

**archived thesis 定义为冻结状态**。当 thesis 状态变为 `archived` 后，其 `current_revision` 和对应 snapshot 成为冻结的最终聚合状态。

**归档后禁止的 mutation**（统一返回 HTTP 409）：

- 编辑 thesis（`PUT /api/thesis/{id}`）
- 关联证据（`POST /api/thesis/{id}/evidence`）
- 取消关联（`DELETE /api/thesis/{id}/evidence/{evidence_id}`）
- 修改 stance（`PUT /api/thesis/{id}/evidence/{evidence_id}`）
- EvidenceRecord 编辑联动（§5.11.6 自动跳过）
- EvidenceRecord 软删除联动（§5.11.6 自动跳过）

**409 响应文案**：

```json
{
  "detail": "已归档的投资逻辑不可修改"
}
```

**archived thesis 的读取方式**：

`GET /api/thesis/{id}` 遇到 archived thesis 时：

- 以 `current_revision` 对应的 snapshot 为权威状态；
- **不通过当前 EvidenceRecord 和当前关联表重新组装内容**；
- 即使证据后来被编辑或软删除，归档 thesis 仍展示归档时的历史证据状态。

这样同时满足：

```text
归档状态冻结
current_revision snapshot 与详情等价
历史证据不受全局证据变化影响
```

**归档是不可逆的最终操作**：归档后不能重新激活（`archived → active` 不允许）。若需重新跟踪，应创建新 thesis。

#### 5.11.8 diff 视图

`GET /api/thesis/{id}/diff?from=1&to=2` 返回两个 snapshot 的字段级 diff（新增/删除/修改的字段值），前端渲染为对比表格。

**第一版限制**：

- 只做字段级比较（字符串/数组变化）；
- **不支持 Markdown 富文本渲染**；
- 不做语义级 diff；
- 证据列表 diff 展示为"新增/移除/stance 变化/字段变化"。

### 5.12 删除证据后如何处理历史版本

**提案：软删除 + 历史快照不清理 + 联动生成新 revision。**

- 删除证据 = 设置 `evidence_records.deleted = 1` + 写入 `deleted_at` + 为所有关联 thesis 生成新 revision（见 §5.11.6）。
- 查询证据列表时 `WHERE deleted = 0` 过滤；但历史 `thesis_revisions.snapshot.evidence_links` 中引用的证据内容仍然保留（snapshot 是不可变的完整 JSON，不因后续删除而改写）。
- diff 视图展示历史版本时，若某条证据已被删除，标注"该证据已删除"但不影响 diff 内容（因 snapshot 已包含完整证据内容）。
- 投资逻辑详情页的"当前证据列表"不展示已删除证据。
- **不提供"级联恢复"**：恢复已删除证据是手动操作，不自动重新关联到投资逻辑。

### 5.13 数据损坏时如何降级与备份

#### 5.13.1 损坏检测与降级

参照 `portfolio.py` 的 `PortfolioDataCorruptedError` 模式：

- 打开数据库时执行 `PRAGMA integrity_check`；若失败，抛 `EvidenceLedgerCorruptedError`。
- 所有读写操作捕获 `sqlite3.DatabaseError`，转换为 `EvidenceLedgerCorruptedError`。
- HTTP 层捕获该异常，返回 500 + 固定安全文案（不透传 SQL 错误或路径）：

  ```text
  投资逻辑数据文件损坏，已停止读写以避免覆盖；请检查 evidence_thesis.db
  ```

- **完整性检查失败时停止该模块的所有读写**，不声称仍处于"只读模式"。
- **不自动修复、不自动重建**：损坏后必须由用户手动从备份恢复。

#### 5.13.2 备份策略（WAL 安全）

**禁止使用普通文件复制作为 SQLite WAL 备份**。原因：WAL 模式下最新已提交数据可能仍在 `evidence_thesis.db-wal` 中，只复制 `.db` 主文件会得到缺少最新事务或不一致的备份。

**使用 Python SQLite backup API**：

```python
source_connection.backup(destination_connection)
```

**建议流程**：

1. 主事务成功提交；
2. 打开临时备份数据库 `evidence_thesis.db.bak.tmp`；
3. 使用 SQLite backup API 生成一致性备份；
4. 备份成功后 `os.replace()` 为 `evidence_thesis.db.bak`（原子替换）；
5. 备份失败**不回滚**已经成功的业务写入，但必须记录安全日志；
6. 不启动无限后台线程（备份在写入事务后同步触发或通过短生命周期任务触发）；
7. **第一版只保留最近一份完整备份**，不保留多份历史备份。

### 5.14 测试策略

**提案：四层测试。**

#### 第一层：存储层专项单测（参照 `test_ttl_cache.py` 模式）

- 证据 CRUD：创建、读取、更新、软删除（含 `deleted_at`）。
- 投资逻辑 CRUD + 版本快照生成（创建即生成 revision 1；编辑生成新 revision）。
- 版本 diff：字段级差异正确性。
- 关联表：多对多关联、取消关联、stance 修改。
- 软删除后查询过滤正确性。
- 事务回滚：模拟写入中途失败，旧数据不变。
- `expected_revision` 冲突 → 409 + 不丢失其他会话修改。
- 损坏检测：注入损坏数据库文件，确认抛出正确异常。
- 完整性检查失败时模块停止读写（不进入只读模式）。
- 外键约束：跨 subject 关联被拒绝。
- 并发写：多线程同时编辑同一 thesis，确认锁保护有效。
- 历史快照内容完整性：编辑后旧 snapshot 不变，新 snapshot 含当时证据最小字段集。

#### 第二层：API 层集成测试（参照 `test_portfolio_advice_api.py` 模式）

- 每个 API 路由的 happy path。
- 校验失败：缺字段、非法枚举值、非法 subject_id 格式 → 400/422。
- 分页参数边界：
  - `limit > 200` → 422。
  - `limit <= 0` → 422。
  - `offset < 0` → 422。
  - 不静默截断。
- DELETE 无 `confirm=true` → 400。
- 未找到资源 → 404。
- 损坏数据库 → 500 + 安全文案。
- `expected_revision` 不匹配 → 409 + 返回 `current_revision`。

#### 第三层：前端单元测试（参照现有 `node --test` 模式）

- API 客户端调用正确性（请求方法、URL、body 字段）。
- diff 视图渲染逻辑（输入两个 snapshot，输出正确 diff 结构）。
- 乐观并发冲突的重试 UI 流程。

#### 第四层：Playwright E2E smoke（至少一条）

**至少一条真实 E2E smoke**：

1. 创建 thesis；
2. 验证 revision 1 存在；
3. 创建 evidence；
4. 关联 evidence（携带 stance）；
5. 验证 `current_revision` 增加；
6. 修改 stance；
7. 验证再次生成 revision；
8. 编辑 thesis；
9. 查看 revision diff；
10. 编辑 evidence；
11. 验证关联 thesis 自动生成新 revision；
12. 软删除 evidence；
13. 当前证据列表不再显示该证据；
14. 历史 revision 仍能显示删除前证据；
15. **当前聚合状态与 current_revision snapshot 等价**。

**继续要求**：

- 全量后端回归（`pytest -m "not live"`）；
- 全量前端测试（`npm test`）；
- build；
- 既有 stock-data smoke E2E 不退化。

#### 不变量测试（必须新增）

**`GET /api/thesis/{id}` 返回的当前聚合状态，必须与 `current_revision` 对应的 `ThesisRevision.snapshot` 等价。**

必须分别覆盖以下场景：

1. 创建 thesis；
2. 编辑 thesis；
3. 关联 evidence；
4. 修改 stance；
5. 取消关联；
6. 编辑 evidence（联动）；
7. 软删除 evidence（联动）；
8. 归档 thesis。

同时验证：

```text
current_revision 每增加一次，必须存在对应的唯一 thesis_revisions 行。
```

#### archived thesis 冻结测试（必须新增）

1. 归档 thesis 后编辑 EvidenceRecord，**不增加**该 thesis 的 revision；
2. 归档 thesis 后软删除 EvidenceRecord，**不增加**该 thesis 的 revision；
3. archived thesis 详情仍显示归档时的证据快照（即使证据已被全局编辑或软删除）；
4. 对 archived thesis 执行编辑、关联、取消关联或 stance 修改，统一返回 **HTTP 409** + `{"detail": "已归档的投资逻辑不可修改"}`；
5. 同一 EvidenceRecord 同时关联 active 和 archived thesis 时，编辑/软删除 EvidenceRecord **只更新 active thesis 的 revision**，archived thesis 的 `current_revision` 保持不变。

### 5.15 迁移策略

**提案：schema_version 表 + 前向迁移脚本。**

- 首次打开数据库：`CREATE TABLE IF NOT EXISTS` 创建所有表 + 写入 `schema_meta`。
- 后续升级：
  - 打开数据库读 `schema_version`。
  - 版本低于代码预期 → 执行迁移脚本（`migrate_v1_to_v2.py` 等）。
  - 迁移在事务内完成，失败则回滚。
  - 迁移成功后更新 `schema_meta.schema_version`。
- **版本高于代码版本 → 拒绝打开**（避免降级损坏）。
- **第一版无历史数据迁移**：v1 是初始版本，无旧数据需迁移。
- 与现有模块的迁移隔离：不动 `ai_results.db` / `daily_review.db` 的迁移逻辑。

### 5.16 不影响现有持仓建议和投资政策的证明

**提案：以下设计决策提供隔离保证。**

1. **独立数据库文件**：`evidence_thesis.db` 与 `portfolio.json`、`ai_results.db`、`daily_review.db` 物理隔离，不共享表、不共享连接。
2. **独立 API 路由前缀**：`/api/thesis` 和 `/api/evidence` 不与 `/api/portfolio`、`/api/portfolio/advice`、`/api/daily-review` 等现有路由冲突。
3. **独立存储模块**：新增 `evidence_thesis_store.py` / `evidence_thesis_service.py` / `evidence_thesis_router.py`，**不 import** `portfolio_advice_service`、`portfolio_advice_policy`、`daily_review`、`chat` 等现有模块。
4. **不修改现有表结构**：不 `ALTER` 任何现有表，不添加外键指向现有表。
5. **不修改现有前端页面核心逻辑**：只在个股页新增可折叠面板（懒加载），不改现有组件状态管理。
6. **独立测试套件**：新增 `test_evidence_thesis_store.py` / `test_evidence_thesis_api.py`，不修改现有测试文件。
7. **回归验证**：实现 PR 的 CI 必须包含现有全部测试（`pytest -m "not live"` + `npm test` + build + 既有 stock-data smoke E2E），证明现有功能未受影响。
8. **关联一致性约束**：`thesis_evidence_links` 关联时校验 thesis 与 evidence 的 `(subject_type, subject_id)` 一致，防止把其他股票的证据误关联到当前股票逻辑；不一致时返回业务错误（不抛裸 SQL 错误）。
9. **新功能路由不写入 app.py**：通过独立 `evidence_thesis_router.py` 暴露，`app.py` 只做 `app.include_router(...)` 最小接入；这不是重构现有全部路由，也不启动 APIRouter 大拆分，仅保证新功能不继续扩大单文件。

## 六、开放问题（实现阶段需确认）

1. `theme` 类型的 `subject_id` 是否需要预定义列表，还是完全自由输入？（MVP 采用自由 slug + 规范化规则，不做预定义列表。）
2. 证据 `claim` 字段是否需要最大长度限制？
3. 投资逻辑 `core_claims` 是否需要逐条关联到具体证据？（第一版只做 thesis-level 关联，不做逐条 claim 关联。）
4. 版本 diff 是否需要支持富文本（Markdown）渲染？（第一版只显示纯文本和数组差异，不支持。）
5. 备份策略是否需要保留多个历史备份？（第一版只保留最近一份一致性备份。）
6. 是否需要在投资逻辑详情页展示"相关复盘结论"？（第一版不做跨模块引用。）

## 七、非目标与暂缓

- 不做自动证据抓取。
- 不做 AI 自动生成或修改投资逻辑（包括 `change_summary` 不由 AI 生成）。
- 不做持仓建议自动引用证据（路线图后续阶段）。
- 不做复杂知识图谱或向量搜索。
- 不做多用户权限或云端同步。
- 不做与 free-stockdb 集成。
- 不做跨模块引用每日复盘结论。
- 不引入 `industry` 类型（MVP 只保留 stock/sector/theme）。
- 不引入 ULID 或其他第三方 ID 库（使用标准库 `uuid.uuid4().hex`）。
- 不修改路线图（`product-roadmap-next-phase.md`）的优先级顺序。

## 八、文档内部一致性核对

- `supports` 字段已从 EvidenceRecord 移除，立场改为 `thesis_evidence_links.stance`。
- **ThesisRevision 定义为聚合状态版本**（thesis 主表 + 当前有效关联 + 当时 EvidenceRecord 最小字段集）。
- **所有非归档 thesis 的聚合状态 mutation 都会生成新 revision**（创建、编辑、归档、关联、修改 stance、取消关联、evidence 编辑联动、evidence 软删除联动）。
- **archived thesis 冻结**：归档后 `current_revision` 不再变化，所有 mutation 返回 409，EvidenceRecord 编辑/软删除不联动 archived thesis。
- **EvidenceRecord 编辑和软删除使用完全一致的联动范围**（`status != 'archived'`），不存在"编辑跳过 archived、软删除联动所有"的矛盾。
- `current_revision` 始终对应一条已存在的 `thesis_revisions.revision_number`，不存在"主表当前版本在版本表中缺失"的状态。
- **`GET /api/thesis/{id}` 返回的当前聚合状态 ≡ `current_revision` 对应的 `ThesisRevision.snapshot`**（archived thesis 以 snapshot 为权威，不重新组装）。
- 创建 thesis 即生成 revision 1（不再有"revision 1 不存在"的情况）。
- `source_date` 允许为空（research_note、口头信息、无发布日期材料）；`accessed_at` 始终必填。
- `source_date` 有值时必须是有效 ISO 8601 date。
- 所有服务端 datetime 使用 UTC ISO 8601。
- `change_summary` 第一版由用户填写，可提供默认值，但不称为 AI 自动生成。
- `core_claims` 第一版采用 thesis-level 证据关联，不增加逐条 claim 关联。
- diff 第一版只显示纯文本和数组差异，不支持 Markdown 富文本渲染。
- 第一版不跨模块引用每日复盘结论。
- 第一版备份只保留最近一份一致性备份。
- 之前的"见 §4.12"应为"见 §5.12"（本文档统一使用 §5.x 编号）。
- PRAGMA 示例为合法 Python（`--` 注释改为 `#` 注释；只读连接不修改 journal mode）。
- 分页规则无歧义（`limit > 200` / `limit <= 0` / `offset < 0` 统一返回 422，不静默截断）。
- 重复索引已删除（不再为 `thesis_evidence_links(thesis_id)` 单独建索引，主键已支持前缀查询）。
- 历史 evidence snapshot 最小字段集明确（含 `evidence_type`，不再使用"完整内容"模糊表述）。

## 九、下一步

本设计文档通过审查后：

1. 在 `design/evidence-thesis-ledger-mvp` 分支基础上创建实现分支（如 `feat/evidence-thesis-ledger-mvp`）。
2. 按 §5.3 表结构实现存储层 `evidence_thesis_store.py`。
3. 按业务规则实现服务层 `evidence_thesis_service.py`（事务、乐观并发、关联校验、EvidenceRecord 联动 revision、备份）。
4. 按 §5.7 路由实现 API 层 `evidence_thesis_router.py`，在 `app.py` 中仅 `app.include_router(...)`。
5. 按 §5.8 页面入口实现前端。
6. 按 §5.14 测试策略编写四层测试（含不变量测试）。
7. 建立 Draft PR，CI 全绿后申请合并。

实现阶段仍遵守"不并行启动多个功能"的治理要求。
