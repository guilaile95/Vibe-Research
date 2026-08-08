# BK-11 short-term fact store v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | GO for snapshot store candidate |
| store candidate | 通过（SQLite 持久化、失败关闭、只读查询） |
| production integration | not authorized |
| Blocker 2 | OPEN（未评估/未改变） |
| Blocker 3 | OPEN（未评估/未改变） |
| Blocker 6 | PARTIALLY CLOSED（未评估/未改变） |
| implementation_allowed(layered_promotion_rates) | false |

本模块不宣称 Blocker 2/3/6 已关闭，不宣称 layered_promotion_rates
可实现，不宣称页面或 API 已完成。

## 2. Scope and Non-goals

### Scope

- 只持久化调用方提供的已批准 `short-term-daily-facts-v0.1` envelope
- 按 `(trade_date, session)` 键控：保存（upsert）/ 加载 / 列示
- 非法或伪造 envelope 拒绝保存，失败关闭，不部分写入
- 读操作只读连接，写操作写连接 + WAL

### Non-goals

- 不计算任何指标
- 不验证 consecutive lbc 来源语义
- 不评估 legal-zero 正向来源
- 不接入生产入口 / API / 页面 / 调度器
- 不新增第二套存储体系（沿用主仓库 SQLite 约定）
- 不依赖 live 外部数据

## 3. Stored Contract

v0.1 只接受：

```text
schema_version == "short-term-daily-facts-v0.1"
```

（Slice 2K 日事实组合 envelope，15 字段精确集合）

## 4. Database Path

```text
优先级：
1. 显式参数 db_path（非空）
2. 环境变量 VR_DATA_DIR / short_term_facts.sqlite3
3. ~/.vibe-research/short_term_facts.sqlite3
```

## 5. Schema

```sql
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_snapshots (
    trade_date TEXT NOT NULL,
    session TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    PRIMARY KEY (trade_date, session)
);
```

`init_db()` 幂等；保存操作自动确保 schema 存在。

## 6. Public API

```text
resolve_db_path(explicit_path=None) -> Path
init_db(db_path=None) -> None
save_daily_facts(envelope, db_path=None) -> {trade_date, session,
    schema_version, stored_at}
load_daily_facts(trade_date, session=None, db_path=None) -> dict | None
list_trade_dates(db_path=None) -> list[str]（升序）
list_snapshots(db_path=None) -> list[{trade_date, session,
    schema_version, stored_at}]
```

`load_daily_facts` 省略 session 时返回该日期 `stored_at` 最新的记录。

## 7. Envelope Validation（失败关闭）

保存前严格验证：

```text
type(envelope) is dict（拒绝子类）
schema_version 精确匹配
15 字段精确集合（无额外/缺失字段）
trade_date: 严格 YYYY-MM-DD 真实日历日期
session: 8 会话词表
status: normal / partial / unavailable / invalid
is_final: 严格 bool
source_ids: list[str]
sections: 精确 {facts, ladder, gap}
严格 JSON 树（拒绝 NaN/Infinity/子类）
```

任一违反 -> `FactStoreInvalidEnvelopeError`，不写入任何内容。

## 8. Corruption Handling

```text
数据库文件损坏 -> FactStoreCorruptedError
已存 JSON 不可解析 -> FactStoreCorruptedError
```

## 9. Concurrency

```text
写路径模块级 threading.Lock 串行化
WAL journal + busy_timeout 5000
读路径只读连接（mode=ro, query_only=ON）
```

## 10. Examples

```text
save_daily_facts(envelope, db) ->
  {"trade_date": "2026-07-31", "session": "final",
   "schema_version": "short-term-daily-facts-v0.1", "stored_at": "..."}

load_daily_facts("2026-07-31", "final", db) -> 原 envelope（深度相等）
load_daily_facts("2026-07-31", db_path=db) -> 当日最新 session
list_trade_dates(db) -> ["2026-07-29", "2026-07-30", "2026-07-31"]
```

## 11. Error Contract

```text
FactStoreInvalidEnvelopeError: envelope 非法（拒绝保存）
FactStoreNotFoundError: 预留（v0.1 加载缺失返回 None，不抛出）
FactStoreCorruptedError: 数据库/JSON 损坏
FactStoreError: 基础异常
```

## 12. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_fact_store.py`）：

```text
路径解析优先级（显式 > VR_DATA_DIR > 默认）
init 幂等 / schema 自动创建
保存-加载往返（深度相等）/ 按日期加载最新 session
upsert 覆盖 / list_trade_dates 升序 / list_snapshots 元数据
非法 envelope 拒绝（非 dict、子类、schema、额外/缺失字段、
  非法日期（含 2026-02-30）、非法 session/status、is_final、
  source_ids、sections、NaN）且不写入
损坏 JSON -> FactStoreCorruptedError
损坏 DB 文件 -> FactStoreCorruptedError
VR_DATA_DIR 隔离（临时目录，不触碰真实目录）
与 2K 组合层真实输出的端到端往返
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 13. Limitations

```text
1. v0.1 只接受 daily-facts envelope；其他已批准 envelope 需后续版本
2. upsert 语义：同 trade_date+session 覆盖，不保留历史版本
3. 存储正确性依赖上游 envelope 的正确性（存储层只验证形状）
4. 不接入生产入口；页面/API 未完成
```

## 14. Security Boundaries

```text
不存储密钥 / 持仓 / 账户信息
envelope 内仅含市场事实与元数据
测试一律使用临时目录，不触碰真实 VR_DATA_DIR / 用户目录
```

## 15. GO / CONDITIONAL GO / NO-GO

**GO for snapshot store candidate**

- 失败关闭保存，非法 envelope 零写入
- 只读查询连接，损坏可检测
- 复用主仓库 SQLite 约定
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- 仅支持 daily-facts envelope（v0.1 范围）
- Blocker 2/3/6 未在本轮评估
- 不得宣称页面/API 已完成
```
