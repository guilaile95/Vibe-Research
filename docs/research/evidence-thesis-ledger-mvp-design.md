# 投资逻辑与证据账本 — MVP 技术设计（草案）

> 状态：**设计草案，非最终定案**。所有字段、表结构和 API 路由均为候选提案，需通过审查后方可进入实现阶段。
>
> 基线：`feature/research-system-v01` @ `2aed400623072750dabac0d3f5849aaaf142ff58`
>
> 路线来源：`docs/research/product-roadmap-next-phase.md` §三（P0：投资逻辑与证据账本）

## 一、设计目标

为每只股票、行业或主题维护一份持续更新的投资逻辑，使投资判断可追溯、可更新、可证伪。第一版只做**手工**创建、编辑、关联和版本化，不涉及自动抓取或 AI 自动修改。

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

## 三、核心数据对象（候选字段）

以下字段为第一版候选最小集。字段名、类型和约束在实现前可调整。

### 3.1 EvidenceRecord

证据记录：一条可追溯的信息单元，关联到某个研究对象，支持或反对某条投资逻辑。

```text
id                  主键，全局唯一
subject_type        研究对象类型：stock | sector | industry | theme
subject_id          研究对象标识（股票代码 / 行业 slug / 主题 slug）
evidence_type       证据类型：news | announcement | report | research_note | financial_filing | other
claim               证据核心主张（简短自然语言摘要，非原文复制）
source_title        来源标题
source_url          来源 URL（可选，本地文件类证据无 URL）
source_date         来源发布日期（ISO 8601 date）
accessed_at         获取时间（ISO 8601 datetime，用户录入或系统记录）
classification      分类：fact | inference | unknown
confidence          置信度：high | medium | low
supports            立场：support | oppose | neutral
created_at          记录创建时间
updated_at          记录最后更新时间
```

**classification 语义**

- `fact`：可验证的客观事实（如"公司 Q3 营收同比增长 20%"）。
- `inference`：基于事实的推断（如"毛利率下降可能反映竞争加剧"）。
- `unknown`：信息不足或来源不可靠，暂无法分类。

**supports 语义**

- `support`：支持某条投资逻辑。
- `oppose`：反对某条投资逻辑。
- `neutral`：与投资逻辑相关但无明确方向（如中性事实背景）。

### 3.2 InvestmentThesis

投资逻辑：针对某个研究对象的持续性研究结论，引用证据，有失效条件。

```text
id                      主键，全局唯一
subject_type            研究对象类型（同 EvidenceRecord）
subject_id              研究对象标识（同 EvidenceRecord）
title                   投资逻辑标题
summary                 投资逻辑摘要
status                  状态：active | weakened | invalidated | archived
core_claims             核心观点列表（JSON array of strings）
catalysts               催化因素列表（JSON array of strings）
risks                   主要风险列表（JSON array of strings）
invalidation_conditions 失效条件列表（JSON array of strings）
created_at              创建时间
updated_at              最后更新时间
current_revision        当前版本号（整数，从 1 开始）
```

**status 语义**

- `active`：当前有效。
- `weakened`：部分失效条件已触发，但逻辑未完全推翻。
- `invalidated`：失效条件已满足，逻辑不再成立（保留历史，不删除）。
- `archived`：用户主动归档（如已清仓且不再跟踪）。

### 3.3 ThesisRevision

投资逻辑版本：每次编辑投资逻辑时生成的不可变快照。

```text
id                  主键，全局唯一
thesis_id           关联的投资逻辑 ID
revision_number     版本号（从 1 递增）
snapshot            该版本的完整投资逻辑快照（JSON，包含 title/summary/core_claims 等）
change_summary      变更摘要（用户输入或自动生成）
created_at          版本创建时间
```

**不可变性**：ThesisRevision 记录一旦创建，不允许修改或删除（删除证据时也不删除历史版本，见 §4.12）。

## 四、第一版能力范围

### 4.1 第一版包含

1. 手工创建和编辑投资逻辑（InvestmentThesis）。
2. 手工添加证据（EvidenceRecord）。
3. 证据关联股票或行业（subject_type + subject_id）。
4. 证据支持或反对某条投资逻辑（supports 字段 + 关联表）。
5. 保存投资逻辑版本（ThesisRevision，每次编辑自动生成快照）。
6. 查看两个版本之间的变化（diff snapshot）。
7. 展示事实、推断和未知项（classification 字段）。
8. 数据全部本地存储（SQLite，不云端同步）。
9. 删除操作有确认（前端二次确认 + 后端软删除）。
10. 写入失败不破坏旧数据（事务回滚 + 原子写入）。

### 4.2 第一版暂不包含

- 自动抓取新闻并自动生成证据。
- AI 自动修改投资逻辑。
- 持仓建议自动引用证据。
- 自动交易。
- 自动触发卖出。
- 复杂知识图谱。
- 向量数据库。
- 多用户权限。
- 云端同步。
- 复杂全文搜索。
- 与 free-stockdb 集成。

## 五、技术决策（必须回答的 16 个问题）

### 5.1 使用 SQLite 还是独立 JSON 存储，为什么

**提案：SQLite。**

理由：

- 证据账本需要按 `subject_type`、`subject_id`、`classification`、`supports`、`thesis_id` 等多维度查询，SQLite 的索引和 WHERE 过滤远优于 JSON 全量扫描。
- 版本快照（ThesisRevision）会随时间增长，JSON 文件全量读写成本线性上升；SQLite 按行存取更稳定。
- 需要事务保证（编辑投资逻辑 + 生成版本快照必须原子完成），SQLite 原生支持事务，JSON 文件需要手动实现 tmp + rename。
- 项目已有成熟的 SQLite 存储模式（`ai_result_store.py`、`review_store.py`），复用一致性高。

JSON 仅用于 SQLite 行内的 `payload_json` / `snapshot` 字段（存复杂嵌套结构），不作为顶层存储。

### 5.2 是否复用现有 SQLite 基础设施

**提案：复用模式，但不复用同一数据库文件。**

- **复用模式**：参照 `review_store.py` / `ai_result_store.py` 的"纯存储层"设计——显式接收 `db_path`、无 ORM、`CREATE TABLE IF NOT EXISTS`、CHECK 约束、损坏检测异常类。
- **独立数据库文件**：使用独立文件 `~/.vibe-research/evidence_thesis.db`（可用 `VR_DATA_DIR` 覆盖），不与 `ai_results.db` / `daily_review.db` 共享文件，避免跨模块迁移风险。
- **不修改现有表**：不触碰 `ai_generated_results`、`daily_review_snapshots`、`portfolio.json` 等现有存储。

### 5.3 数据表和索引

**候选表结构**：

```sql
-- 证据表
CREATE TABLE IF NOT EXISTS evidence_records (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','industry','theme')),
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('news','announcement','report','research_note','financial_filing','other')),
    claim TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_url TEXT,
    source_date TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('fact','inference','unknown')),
    confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
    supports TEXT NOT NULL CHECK (supports IN ('support','oppose','neutral')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0  -- 软删除标记：0=正常, 1=已删除
);

-- 投资逻辑表
CREATE TABLE IF NOT EXISTS investment_theses (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','industry','theme')),
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','weakened','invalidated','archived')),
    core_claims TEXT NOT NULL,           -- JSON array
    catalysts TEXT NOT NULL,             -- JSON array
    risks TEXT NOT NULL,                 -- JSON array
    invalidation_conditions TEXT NOT NULL, -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 1
);

-- 投资逻辑版本表（不可变）
CREATE TABLE IF NOT EXISTS thesis_revisions (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    snapshot TEXT NOT NULL,              -- 完整 InvestmentThesis JSON 快照
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    UNIQUE (thesis_id, revision_number)
);

-- 证据-投资逻辑关联表（多对多：一条证据可关联多条逻辑，一条逻辑可引用多条证据）
CREATE TABLE IF NOT EXISTS thesis_evidence_links (
    thesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thesis_id, evidence_id),
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
);
```

**候选索引**：

```sql
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence_records(subject_type, subject_id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_evidence_classification ON evidence_records(classification) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_thesis_subject ON investment_theses(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_thesis_status ON investment_theses(status);
CREATE INDEX IF NOT EXISTS idx_revisions_thesis ON thesis_revisions(thesis_id, revision_number);
CREATE INDEX IF NOT EXISTS idx_links_evidence ON thesis_evidence_links(evidence_id);
```

### 5.4 ID 生成规则

**提案：ULID（Universally Unique Lexicographically Sortable Identifier）。**

- 全局唯一，无需中央分配。
- 可按时间排序（26 字符 Crockford Base32），便于按创建顺序展示。
- 比 UUID v4 更易调试（肉眼可读时间前缀）。
- 实现用纯 Python 库 `ulid-py` 或手写（ULID 规范简单，无外部依赖也可实现）。

**回退方案**：若不引入 `ulid-py`，用 `uuid.uuid4().hex`（32 字符十六进制），牺牲可排序性。

ID 示例：`01H8XGJF2KQ3M4N5P6R7S8T9V0`（ULID）。

### 5.5 Schema 版本

**提案：在数据库中维护 `schema_meta` 表。**

```sql
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- 初始化时写入：INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', 'evidence_thesis_ledger_v1');
```

- 当前版本：`evidence_thesis_ledger_v1`。
- 后续升级时版本号递增（`v2`, `v3`...），迁移脚本按版本号分支执行。
- 打开数据库时先读 `schema_version`，若版本不匹配则拒绝写入并提示用户升级（避免降级损坏）。

### 5.6 原子写入和事务边界

**提案：SQLite WAL 模式 + 显式事务。**

- 打开数据库时 `PRAGMA journal_mode=WAL`（并发读不阻塞写）。
- 每个写操作包裹在 `BEGIN IMMEDIATE ... COMMIT` 中：
  - **编辑投资逻辑**：在同一事务内更新 `investment_theses` 行 + 插入 `thesis_revisions` 快照。任一失败则 `ROLLBACK`，旧数据不受影响。
  - **删除证据**：在同一事务内设置 `evidence_records.deleted=1` + 不删除 `thesis_evidence_links`（保留历史引用）。
- 连接级别用 `threading.Lock` 保护（参照 `portfolio.py` 的 `_LOCK` 模式），避免 SQLite "database is locked"。
- 写入后不额外 `fsync`（SQLite 在 WAL 模式下自行管理持久化；极端崩溃场景由 WAL checkpoint 恢复）。

### 5.7 API 路由

**候选路由**（全部在 `/api/thesis` 和 `/api/evidence` 前缀下）：

```text
# 证据
GET    /api/evidence?subject_type=stock&subject_id=600519   列出证据（按研究对象过滤）
POST   /api/evidence                                         创建证据
GET    /api/evidence/{id}                                    获取证据详情
PUT    /api/evidence/{id}                                    更新证据
DELETE /api/evidence/{id}                                    软删除证据（需 confirm=true 查询参数）

# 投资逻辑
GET    /api/thesis?subject_type=stock&subject_id=600519      列出投资逻辑（按研究对象过滤）
POST   /api/thesis                                            创建投资逻辑
GET    /api/thesis/{id}                                       获取投资逻辑详情（含关联证据）
PUT    /api/thesis/{id}                                       更新投资逻辑（自动生成版本快照）
DELETE /api/thesis/{id}                                       归档投资逻辑（status→archived，不物理删除）

# 投资逻辑版本
GET    /api/thesis/{id}/revisions                             列出所有版本
GET    /api/thesis/{id}/revisions/{rev}                       获取指定版本快照
GET    /api/thesis/{id}/diff?from=1&to=2                      比较两个版本的差异

# 证据关联
POST   /api/thesis/{id}/evidence                              关联证据到投资逻辑
DELETE /api/thesis/{id}/evidence/{evidence_id}                取消关联
```

**约束**：

- DELETE 操作必须带 `confirm=true` 查询参数，否则返回 400。
- 所有写操作返回最新数据快照（不返回裸状态码）。
- 错误用与现有端点一致的 `{detail: "..."}` 格式。
- 不接受客户端传入 `id`、`created_at`、`updated_at`、`current_revision`（服务端生成）。

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

### 5.9 股票与行业的统一 subject 表达

**提案：`subject_type` + `subject_id` 二元组。**

| subject_type | subject_id 示例 | 说明 |
|---|---|---|
| `stock` | `600519` | A股 6 位代码（与现有 `_CODE_RE = ^\d{6}$` 一致） |
| `sector` | `pcb` | 板块 slug（与现有 `sector_research_data` 的 workspace slug 一致） |
| `industry` | `semiconductors` | 行业 slug（若与 sector 区分需要） |
| `theme` | `ai_inference` | 自由主题 slug（用户自定义） |

- 同一证据或投资逻辑只能关联一个 subject（不支持跨 subject 的"组合逻辑"，留待后续版本）。
- subject_id 不做外键约束（股票/行业数据来自外部数据源，可能动态变化）；只做格式校验（stock 必须是 6 位数字，sector/industry/theme 必须是合法 slug）。
- 前端通过 subject_type 决定跳转目标（stock → 个股页，sector → 板块页）。

### 5.10 证据来源字段如何保持可追溯

**提案：四个必填来源字段 + 一个可选 URL。**

| 字段 | 必填 | 说明 |
|---|---|---|
| `source_title` | 是 | 来源标题（用户录入，如"贵州茅台 2025 年三季报"） |
| `source_url` | 否 | 来源 URL（本地文件或口头信息可留空） |
| `source_date` | 是 | 来源发布日期（区分"信息产生时间"与"用户录入时间"） |
| `accessed_at` | 是 | 用户获取该信息的时间（证明"何时看到"，即使 source_date 很早） |

- `source_date` 和 `accessed_at` 分开，避免把"旧新闻当新证据"。
- `claim` 字段存用户摘要（非原文复制），避免版权问题，同时保留可追溯的 source_url。
- 若来源是本地文件（如 PDF 研报），`source_url` 留空，`source_title` 写文件名，未来可扩展 `source_file_id` 字段关联文件存储。

### 5.11 版本变更如何生成

**提案：每次 PUT /api/thesis/{id} 自动生成一个 ThesisRevision。**

流程：

1. 客户端 PUT 请求携带修改后的 thesis 字段。
2. 服务端在事务内：
   a. 读取当前 thesis 行（含 `current_revision`）。
   b. 将当前 thesis 完整快照存入 `thesis_revisions`（`revision_number = current_revision`，作为修改前的存档）。
   c. 更新 `investment_theses` 行为新字段，`current_revision += 1`。
   d. 若客户端提供了 `change_summary`，写入 revision；否则用默认值"编辑投资逻辑"。
3. 事务提交。任一步失败则回滚，旧版本和旧快照不受影响。

**diff 视图**：`GET /api/thesis/{id}/diff?from=1&to=2` 返回两个 snapshot 的字段级 diff（新增/删除/修改的字段值），前端渲染为对比表格。

**限制**：第一版 diff 只做字段级比较（字符串/数组变化），不做语义级 diff。

### 5.12 删除证据后如何处理历史版本

**提案：软删除 + 历史快照不清理。**

- 删除证据 = 设置 `evidence_records.deleted = 1`，不物理删除行，不删除 `thesis_evidence_links`。
- 查询证据列表时 `WHERE deleted = 0` 过滤；但历史 `thesis_revisions.snapshot` 中引用的证据 ID 仍然保留（快照是不可变的完整 JSON，不因后续删除而改写）。
- diff 视图展示历史版本时，若某条证据已被删除，标注"该证据已删除"但不影响 diff 内容。
- 投资逻辑详情页的"当前证据列表"不展示已删除证据。
- **不提供"级联恢复"**：恢复已删除证据是手动操作，不自动重新关联到投资逻辑。

### 5.13 数据损坏时如何降级

**提案：检测即停止 + 安全文案 + 不覆盖。**

参照 `portfolio.py` 的 `PortfolioDataCorruptedError` 模式：

- 打开数据库时执行 `PRAGMA integrity_check`；若失败，抛 `EvidenceLedgerCorruptedError`。
- 所有读写操作捕获 `sqlite3.DatabaseError`，转换为 `EvidenceLedgerCorruptedError`。
- HTTP 层捕获该异常，返回 500 + 固定安全文案（不透传 SQL 错误或路径）：
  ```text
  投资逻辑数据文件损坏，已停止读写以避免覆盖；请检查 evidence_thesis.db
  ```
- **不自动修复、不自动重建**：损坏后只读模式，要求用户手动从备份恢复。
- 备份策略：每次成功写入后，异步复制一份 `evidence_thesis.db.bak`（参照 `portfolio.py` 的 `.bak` 模式），保留最近一次完整状态。

### 5.14 测试策略

**提案：三层测试。**

**第一层：存储层专项单测**（参照 `test_ttl_cache.py` 模式）

- 证据 CRUD：创建、读取、更新、软删除。
- 投资逻辑 CRUD + 版本快照生成。
- 版本 diff：字段级差异正确性。
- 关联表：多对多关联、取消关联。
- 软删除后查询过滤正确性。
- 事务回滚：模拟写入中途失败，旧数据不变。
- 损坏检测：注入损坏数据库文件，确认抛出正确异常。
- 并发写：多线程同时编辑同一 thesis，确认锁保护有效。

**第二层：API 层集成测试**（参照 `test_portfolio_advice_api.py` 模式）

- 每个 API 路由的 happy path。
- 校验失败：缺字段、非法枚举值、非法 subject_id 格式 → 400/422。
- DELETE 无 `confirm=true` → 400。
- 未找到资源 → 404。
- 损坏数据库 → 500 + 安全文案。

**第三层：前端关键路径**（参照现有 `node --test` 模式）

- API 客户端调用正确性（请求方法、URL、body 字段）。
- diff 视图渲染逻辑（输入两个 snapshot，输出正确 diff 结构）。

**不做的测试**：

- 不做 E2E（第一版功能简单，单测 + 集成测试覆盖足够）。
- 不做性能测试（数据量小，SQLite 单文件足够）。

### 5.15 迁移策略

**提案：schema_version 表 + 前向迁移脚本。**

- 首次打开数据库：`CREATE TABLE IF NOT EXISTS` 创建所有表 + 写入 `schema_meta`。
- 后续升级：
  - 打开数据库读 `schema_version`。
  - 若版本低于代码预期，执行迁移脚本（`migrate_v1_to_v2.py` 等）。
  - 迁移在事务内完成，失败则回滚。
  - 迁移成功后更新 `schema_meta.schema_version`。
- **不支持降级**：若数据库版本高于代码预期，拒绝打开并提示用户升级代码。
- **第一版无历史数据迁移**：v1 是初始版本，无旧数据需迁移。
- 与现有模块的迁移隔离：不动 `ai_results.db` / `daily_review.db` 的迁移逻辑。

### 5.16 不影响现有持仓建议和投资政策的证明

**提案：以下设计决策提供隔离保证。**

1. **独立数据库文件**：`evidence_thesis.db` 与 `portfolio.json`、`ai_results.db`、`daily_review.db` 物理隔离，不共享表、不共享连接。
2. **独立 API 路由前缀**：`/api/thesis` 和 `/api/evidence` 不与 `/api/portfolio`、`/api/portfolio/advice`、`/api/daily-review` 等现有路由冲突。
3. **独立存储模块**：新增 `evidence_thesis_store.py`，不 import `portfolio.py`、`portfolio_advice_service.py`、`ai_result_service.py`、`daily_review_cache.py` 等现有模块。
4. **不修改现有表结构**：不 `ALTER` 任何现有表，不添加外键指向现有表。
5. **不修改现有前端页面核心逻辑**：只在个股页新增可折叠面板（懒加载），不改现有组件状态管理。
6. **独立测试套件**：新增 `test_evidence_thesis_store.py` / `test_evidence_thesis_api.py`，不修改现有测试文件。
7. **回归验证**：实现 PR 的 CI 必须包含现有全部测试（`pytest -m "not live"` + `npm test`），证明现有功能未受影响。

## 六、开放问题（实现阶段需确认）

1. `theme` 类型的 `subject_id` 是否需要预定义列表，还是完全自由输入？
2. 证据 `claim` 字段是否需要最大长度限制？
3. 投资逻辑 `core_claims` 等数组字段是否需要逐条关联到具体证据（第一版只做 thesis-level 关联）？
4. 版本 diff 是否需要支持富文本（Markdown）渲染？
5. 备份策略是否需要保留多个历史备份（而非仅最近一份）？
6. 是否需要在投资逻辑详情页展示"相关复盘结论"（跨模块引用，第一版不做）？

## 七、非目标与暂缓

- 不做自动证据抓取。
- 不做 AI 自动生成或修改投资逻辑。
- 不做持仓建议自动引用证据（路线图后续阶段）。
- 不做复杂知识图谱或向量搜索。
- 不做多用户权限或云端同步。
- 不做与 free-stockdb 集成。
- 不修改路线图（`product-roadmap-next-phase.md`）的优先级顺序。

## 八、下一步

本设计文档通过审查后：

1. 在 `design/evidence-thesis-ledger-mvp` 分支基础上创建实现分支（如 `feat/evidence-thesis-ledger-mvp`）。
2. 按 §5.3 表结构实现存储层 `evidence_thesis_store.py`。
3. 按 §5.7 路由实现 API 层。
4. 按 §5.8 页面入口实现前端。
5. 按 §5.14 测试策略编写三层测试。
6. 建立 Draft PR，CI 全绿后申请合并。

实现阶段仍遵守"不并行启动多个功能"的治理要求。
