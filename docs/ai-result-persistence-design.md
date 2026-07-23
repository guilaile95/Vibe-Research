# AI 生成结果持久化与每日复盘页面重排设计

状态：设计已确认，尚未开始功能编码。

基础分支：`feature/research-system-v01`
基础提交：`feba6fedd3a17a8275b0aa9bbd760bd891b0e028`

## 1. 目标与非目标

### 目标

- 每日复盘 AI 和持仓操作建议按交易日保存当天最新版，重新打开页面后自动恢复。
- 复用现有 `daily_reviews.sqlite3`，新增独立表，不影响市场复盘快照历史。
- 生成失败、断流、校验失败或保存失败时保留旧结果。
- 每日复盘 AI 只有在上游模型流真实完成且持久化成功后才向前端发送最终 `done`。
- 持仓建议保存 validator、执行约束和账户指标处理后的权威结构化结果。
- 持仓变化后保留旧建议，并显示固定的过期提示。
- 每日复盘页面先展示关键市场数据；保留原有数据模块，可新增摘要，尽量不删除。

### 非目标

- 不修改或复用 `daily_review_snapshots` 表。
- 不新增第二个 SQLite 文件。
- 不以 `localStorage` 作为权威或唯一存储。
- 不保存 API Key、Authorization、Base URL、完整 Prompt、完整模型上下文或未经校验的模型原始响应。
- 不自动定时生成、不在页面打开时调用模型、不因持仓变化自动删除或重新生成建议。
- 本设计阶段不创建数据库表、不修改 API、不修改前端流解析器、不编写功能或测试代码，也不执行功能测试。

## 2. 现有架构事实

- 每日复盘历史使用 `daily_reviews.sqlite3` 中的 `daily_review_snapshots` 表，一天可保存多份不同内容的市场快照。
- `POST /api/daily-review/analyze` 当前通过 NDJSON 输出 `delta`、`done`、`error`。
- `chat.prepare_daily_review_messages()` 当前内部调用一次 `daily_review.generate_daily_review()`，但只返回 messages，调用方无法复用同一份 review 作为保存元数据。
- `_iter_sse_deltas()` 当前遇到上游 `[DONE]` 时直接 `return`，没有把“是否收到 `[DONE]`”传给调用方；上游 EOF 也会正常结束迭代。
- `stream_messages()` 当前在 `_iter_sse_deltas()` 结束后自行发送业务层 `done`，因此上游 EOF 但未收到 `[DONE]` 仍可能被误判为成功。
- `cli_runtime.run_cli_stream()` 当前对超时、输出结束后进程不退出和非零退出码均抛异常，并在 finally 中终止仍存活的子进程；实施时仍须用测试固定退出码、取消和异常关闭语义。
- 前端 `streamNdjson()` 当前没有 `sawDone` / `sawError`，网络流结束且没有 error 时可能返回成功。
- 持仓建议已经经过严格 JSON 解析、validator、执行约束和账户指标处理，但结果只保存在前端 Zustand 运行内存。

## 3. 数据库设计

复用 `daily_reviews.sqlite3`，新增表：

```sql
CREATE TABLE IF NOT EXISTS ai_generated_results (
    result_type TEXT NOT NULL
        CHECK (result_type IN ('daily_review_ai', 'portfolio_advice')),
    trade_date TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_fingerprint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (result_type, trade_date)
);
```

规则：

- 唯一结果类型为 `daily_review_ai`、`portfolio_advice`。
- 主键 `(result_type, trade_date)` 保证同类结果每个交易日只保留最新版。
- `created_at` 首次写入后不变；UPSERT 更新 `updated_at` 和新结果字段。
- `daily_review_ai.input_fingerprint` 为 `NULL`；`portfolio_advice.input_fingerprint` 必填。
- `schema_version` 分类型演进，初始值建议为 `daily_review_ai.v1`、`portfolio_advice.v1`。
- 日期、时间、模型名、结果类型、JSON 可序列化性和 payload 结构由服务层严格校验。
- 不依赖 SQLite JSON1 扩展，保证本机 Python 标准库 SQLite 可用。

每日复盘 AI payload：

```json
{
  "markdown": "完整 Markdown",
  "source_review_generated_at": "2026-07-23 15:20:00",
  "source_data_cutoff": "2026-07-23 15:00:00"
}
```

持仓建议 payload 保存现有 validator 和账户指标处理后的完整权威结果，不保存模型原始文本。

## 4. 模块职责

### `backend/ai_result_store.py`

- 幂等建表、索引和 SQLite 连接。
- 确定性 JSON 序列化与反序列化。
- 按结果类型和交易日期查询，以及按类型查询最新记录。
- 事务 UPSERT 和回滚。
- 将数据库记录转换为内部对象。
- 对损坏 payload 抛内部专用异常。
- 不包含 HTTP、模型调用、持仓读取、交易日推断或用户文案。

### `backend/ai_result_service.py`

- 校验 `result_type`、交易日期、模型信息和 payload。
- 规范化 provider。
- 构造每日复盘 AI 和持仓建议保存对象。
- 生成持仓指纹并计算 `stale`。
- 管理“恢复路径”的缓存/数据库回退规则。
- 清理 API 返回对象，防止敏感信息进入持久层或响应。

### `backend/chat.py`

- 提供一次性每日复盘分析准备结果。
- 严格确认上游 API SSE `[DONE]`。
- 仅在真实完成时产生内部完成信号。
- 不直接包含 SQLite SQL。

### `backend/cli_runtime.py`

- 保证 CLI 正常退出且退出码为 0 才算真实完成。
- 超时、取消、异常关闭、非零退出码均抛异常。
- 若实现审计发现取消传播或退出码处理仍有缺口，本次必须修复并补测试。

### `backend/app.py`

- HTTP 参数、状态码、安全文案和 NDJSON 包装。
- 在生成成功路径调用服务层保存。
- 保存成功后才发送最终业务层 `done` 或返回 HTTP 200。
- 不堆放 SQL、指纹算法或持久化策略。

## 5. 每日复盘每次请求只聚合一次

新增内部准备函数，名称建议为 `prepare_daily_review_analysis()`：

```python
{
    "review": review,
    "context_json": context_json,
    "messages": messages,
}
```

约束：

1. 每次分析请求只调用一次 `daily_review.generate_daily_review()`。
2. Prompt、`trade_date`、来源 `generated_at`、`data_cutoff` 和保存元数据全部来自同一份 review。
3. context 只构建一次。
4. 不改变公开 HTTP 请求体。
5. 不把完整 review 或 context 返回前端。
6. 禁止 app.py 为取日期生成一次 review、chat.py 又为 Prompt 生成一次 review。

## 6. 上游模型流真实完成条件

真实完成链路：

```text
上游模型流真实完成
→ 结果校验通过
→ 持久化成功
→ 后端业务层发送最终 done
→ 前端 sawDone=true 且 sawError=false
→ 页面任务成功
```

### API SSE

- `_iter_sse_deltas()` 或替代解析器必须把“收到上游 `[DONE]`”作为显式结果返回。
- 上游 EOF 但未收到 `[DONE]` 视为异常完成，不得等同于正常结束。
- JSON 噪声行可以按现有兼容策略忽略，但不能用 EOF 代替 `[DONE]`。
- 请求异常、读取异常、取消、EOF without `[DONE]` 均不得产生业务层 `done`。
- 对前端发送安全的流内 `error`，不得泄露认证头、完整响应体或内部路径。

### CLI

- CLI stdout EOF 不是完成条件。
- 子进程必须在时限内正常退出且退出码为 0。
- 超时、取消、异常关闭、输出结束但进程不退出、非零退出码均不得产生业务层 `done`。
- 当前 `run_cli_stream()` 已检查超时和退出码，但本次仍必须验证取消传播、生成器提前关闭和子进程回收。

## 7. 后端最终 `done` 语义

每日复盘 AI 的生成包装器按以下顺序工作：

1. 使用单次聚合准备结果。
2. 转发 `delta`，并在后端累计完整 Markdown。
3. 捕获内部上游完成信号，但暂不向前端转发业务层 `done`。
4. 校验 Markdown 非空、来源 review 元数据有效。
5. 一次性事务 UPSERT。
6. 数据库提交成功后，才发送最终业务层 `done`。
7. 任一失败发送 `error`，不发送 `done`，旧记录不变。

不得在每个 delta 阶段写数据库。客户端断开或生成器中途关闭时，不得进入成功保存路径。

## 8. 前端 `sawDone` / `sawError` 语义

公共 NDJSON 解析器增加 `sawDone`、`sawError`：

```text
收到 error                         → 失败
流结束但 sawDone=false             → 失败
同时出现 error 和 done             → 按失败处理
只有 sawDone=true 且 sawError=false → 成功
```

局部 delta 可以临时展示，但不得替换已恢复的权威旧结果。只有最终成功后，Zustand 才更新成功结果和完成时间。

## 9. 持仓建议保存时机

1. `prepare_portfolio_advice_messages()` 读取本次实际参与分析的持仓快照和 fresh 每日复盘。
2. 基于这份持仓快照立即生成指纹，避免模型返回后重新读取持仓造成错配。
3. 调用模型并取得完整文本。
4. 严格解析 JSON。
5. 通过现有 validator 和执行约束。
6. 附加账户资金与权威计算指标。
7. 构造最终权威结果。
8. 事务 UPSERT 成功后才返回 HTTP 200。

解析、validator、账户指标或保存失败均不覆盖旧结果。空仓生成继续返回现有 409，也不删除旧建议。

## 10. 持仓指纹算法

只使用本次实际参与分析的持仓快照，提取：

```json
[
  {"code": "000001", "shares": 100, "cost": 12.5}
]
```

步骤：

1. 校验六位代码、shares、cost；拒绝布尔值、NaN 和无穷数。
2. 按 `code` 升序排序。
3. 使用 `ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`、`allow_nan=False` 生成确定性 JSON。
4. 对 UTF-8 字节计算 SHA-256，保存小写十六进制字符串。

持仓顺序变化不影响指纹；数量、成本、新增、删除或清仓导致 `stale=true`。固定提示：

> 持仓已发生变化，该建议基于生成时的持仓，可能已经过期。

不自动删除，不自动重新生成。

## 11. 事务与失败不覆盖策略

模型调用、内容校验、validator 和 payload 序列化均在写事务前完成。写入使用单事务 UPSERT：

```sql
BEGIN IMMEDIATE;

INSERT INTO ai_generated_results (...)
VALUES (...)
ON CONFLICT(result_type, trade_date) DO UPDATE SET
    schema_version = excluded.schema_version,
    payload_json = excluded.payload_json,
    generated_at = excluded.generated_at,
    model_provider = excluded.model_provider,
    model_name = excluded.model_name,
    input_fingerprint = excluded.input_fingerprint,
    updated_at = excluded.updated_at;

COMMIT;
```

- `created_at` 不在冲突更新列表中。
- 任何异常均回滚；不先删除再插入。
- 提交成功前旧记录始终有效。
- 保存失败时生成接口不报告成功。
- 损坏 payload 不返回半截数据，不泄露数据库路径、SQL 或 traceback。

## 12. 恢复路径与生成路径

### 生成路径

- 每日复盘 AI 和持仓建议必须使用本次请求唯一一次生成的 fresh 结构化复盘。
- 该 review 同时用于 Prompt、交易日和保存元数据。
- 生成路径可以调用模型，成功后可以写 `ai_generated_results`。

### 恢复路径

- 只读，不调用模型，不写历史，不触发 fresh `generate_daily_review()`。
- 每日复盘页先加载结构化展示数据，再显式用其 `trade_date` 查询 AI 结果。
- 持仓页优先使用现有每日复盘展示/缓存路径取得最近交易日。
- 展示缓存没有可用交易日期时，按 `result_type` 查询 `ai_generated_results` 最新一条，并返回记录自身的 `trade_date`。
- 页面明确显示结果所属交易日。
- 不使用浏览器自然日期或服务器自然日期推断交易日。

## 13. Provider 兼容策略

- `model_name` 必须是非空字符串。
- provider 非空时保存原值，包括 `cli-*`。
- provider 为空且不是 CLI 接入时，规范化为 `api-compatible`。
- 只保存 provider 和 model，不保存 API Key、Authorization 或 Base URL。
- 不能因现有 API 兼容接入的 provider 为空而让已成功生成的结果在持久化校验阶段失败。

## 14. API 契约

```http
GET /api/ai-results/{result_type}?trade_date=YYYY-MM-DD
```

存在记录：

```json
{
  "data": {
    "result_type": "portfolio_advice",
    "trade_date": "2026-07-23",
    "schema_version": "portfolio_advice.v1",
    "payload": {},
    "generated_at": "2026-07-23 15:30:00",
    "model_provider": "cli-codex",
    "model_name": "xxx",
    "stale": false
  }
}
```

无记录统一返回 `200 {"data": null}`，作为页面正常空状态。

- 每日复盘页必须显式传 trade_date。
- 持仓页可显式传缓存交易日；省略时只允许走展示缓存或数据库最新记录回退，不允许 fresh 聚合。
- 非法 trade_date 返回 422。
- result_type 由路径枚举约束，只允许两种值。
- 不新增允许前端提交 Markdown 或自定义结构化建议的保存接口。

## 15. 页面状态机

两页均区分：

```text
idle → restoring → empty | restored | restore_error
restored | empty → generating → success | generation_error
```

- generating 期间保留 restored 旧结果。
- success 才替换旧结果。
- generation_error 显示错误并继续展示旧结果。
- 持仓变化后重新读取保存结果以取得后端计算的 stale，不自动调用模型。

每日复盘页面按以下层级重排，保留现有内容：

1. 大盘指数、全球市场、市场广度、短线情绪。
2. 全市场成交额榜、板块强弱亮点、板块涨幅排名。
3. 关注股票。
4. AI 当日复盘，显示交易日、生成时间、模型和来源数据时间。
5. 历史复盘、详情和快照对比。

可以新增市场核心摘要，但不替代或删除原始明细。持仓页保留持仓表、账户指标、账户级建议和逐股建议。

## 16. 预计修改文件

新增：

```text
backend/ai_result_store.py
backend/ai_result_service.py
backend/tests/test_ai_result_store.py
backend/tests/test_ai_result_service.py
backend/tests/test_ai_result_api.py
```

预计修改：

```text
backend/app.py
backend/chat.py
backend/cli_runtime.py（仅当完成语义审计或测试发现缺口）
backend/portfolio_advice_service.py
backend/tests/test_daily_review_ai_api.py
backend/tests/test_daily_review_ai_chat.py
backend/tests/test_portfolio_advice_api.py
frontend/src/lib/api.ts
frontend/src/stores/dailyReviewAiTaskStore.ts
frontend/src/stores/portfolioAdviceTaskStore.ts
frontend/src/pages/DailyReview.tsx
frontend/src/pages/Portfolio.tsx
```

可能修改两个任务状态指示组件。除非路径解析确需抽取，否则不修改 `review_store.py`、`review_history.py`。

## 17. 测试矩阵

### 数据库与服务层

- 首次保存；同类型同交易日覆盖；不同日期和不同类型独立。
- created_at 不变、updated_at 更新。
- 初始化幂等；重复和并发 UPSERT。
- 非法类型、非法日期、空或不可序列化 payload、损坏 payload。
- 事务或提交失败不破坏旧记录。
- provider 空值规范化；model 空值拒绝。

### API SSE 与 CLI 完成语义

- API 收到 `[DONE]` 才成功。
- API EOF without `[DONE]`、请求异常、读取异常和取消均失败且无业务层 done。
- CLI 退出码 0 才成功。
- CLI 非零退出、超时、取消、异常关闭、stdout EOF 后进程不退出均失败。
- 失败错误安全，不泄露敏感数据。

### 每日复盘 AI

- 每请求只调用一次 `generate_daily_review()`，Prompt 与保存元数据来自同一对象。
- 非空 Markdown、真实完成、保存成功后才发送最终 done。
- 空结果、流 error、中途断流、无真实完成信号、保存失败均不保存。
- 失败后旧记录仍可恢复。
- 保存来源 generated_at 和 data_cutoff。
- 恢复不触发模型或 fresh 聚合。

### 持仓建议

- validator 和账户指标处理后保存权威结果。
- 原始模型文本不保存。
- JSON/validator/保存失败不覆盖旧记录。
- 指纹基于本次实际分析的持仓快照。
- 数量、成本、新增、删除、清仓 stale=true；顺序变化不影响指纹。
- 空仓生成 409，旧结果仍可读。

### API 与前端

- 有记录、无记录、非法类型、非法日期和数据库异常。
- 省略 trade_date 时只走缓存或数据库最新记录，不 fresh 聚合。
- 页面恢复不生成；loading、empty、error、restored 状态分离。
- 重新生成成功替换，失败保留旧结果。
- sawDone / sawError 四种组合符合规则。
- 重复点击防护、持仓过期提示、移动端无横向溢出。

## 18. Git 实施流程

设计文档先在 `codex/ai-result-persistence` 单独提交并推送。主审通过 GitHub 连接创建 Draft PR，Base 为 `feature/research-system-v01`。设计审核通过后，继续在同一分支和同一 Draft PR 中添加实现 commit。

实施前再次核验基线和工作区；只提交本任务文件。完成实现后运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -m "not live"
cd ..

cd frontend
npm run build
cd ..

git diff --check origin/feature/research-system-v01...HEAD
```

不得使用 `git reset --hard`、`git checkout .`、`git restore .`、`git clean` 或普通 `--force`。如 rebase 后必须更新远端，只允许 `--force-with-lease`。

## 19. 明确不做内容

- 本设计提交不含后端、前端、测试、数据库 schema、CI、依赖或 lockfile 改动。
- 不声称功能已完成或测试已通过。
- 不转 Ready、不合并 PR、不删除分支、不修改稳定分支。
- 不在设计审核前编写逐步实施计划或开始功能编码。
