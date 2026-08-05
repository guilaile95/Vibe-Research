# BK-11 Daily Review 生产接入 v0.1（短线市场历史）

> 阶段：bk11-daily-review-history-v0.1
> 分支：feat/bk11-daily-review-history-v0.1
> 目标 base：17c7f1dadd16a3ced2b73588fa9d5a987fa86520（feature/research-system-v01）

## 一、本轮交付

1. 只读历史查询 API：`GET /api/market/bk11-history`
2. 历史存储最小连接：直接复用已批准的 `short_term_fact_store` 读接口，
   不创建第二套存储
3. Data Health source：`bk11_history`（BK-11 短线历史）
4. Daily Review 页面「短线市场历史」区块（独立组件 + view helper）
5. 后端 / 前端单元 / 浏览器 E2E 测试与文档

## 二、生产快照写入状态（规则 C：上游输入缺失阻塞）

当前生产代码没有任何路径调用：

```text
fetch_final_limit_up_pool_snapshot
compute_daily_facts
save_daily_facts
```

仓库证据：`rg` 显示上述函数仅存在于已批准的 BK-11 纯计算模块与其自身测试中，
无生产调用方。Daily Review 现有数据只保留 emotion 聚合子集，无法无损转换为
producer 输入；`market.get_short_term_emotion()` 会发起 live 请求（未授权）。

因此本轮按规则 C 处理：

- 完成只读 API、Data Health 与页面空状态接入；
- 不得用 fixture 或示例数据伪装成生产数据；
- 页面在无快照时显示空状态并如实说明「生产快照写入仍受上游输入缺失阻塞」；
- 不新建外部数据源、不发起 live 探测。

## 三、历史查询 API

### 路由

```text
GET /api/market/bk11-history?days=5
```

`days`：默认 5；允许 1..60；bool / 零 / 负数 / 超界 → HTTP 400；非整数 → 422。

### 响应 envelope（`{"data": {...}}`）

```text
schema_version: bk11-history-query-v0.1
status: empty | normal | partial | unavailable | error
window: { requested, snapshot_count }
trade_date: 最新权威快照业务日期（无快照为 null）
data_time: 最新快照 snapshot_at / fetched_at（取自存储，不使用系统时间）
snapshots: 窗口内每日权威快照元数据（trade_date 升序）
latest: 最新权威 daily-facts envelope（原样透传）
delta: compute_fact_compare(latest, 最近前序) 输出；仅一天时为 null
summary: compute_fact_summary(窗口 envelopes) 输出
digest: build_fact_digest(summary) 输出（确定性文本）
reason_codes / warnings / limitations: 稳定公开文案
```

### 只读边界

- GET 不写数据库、不创建数据库文件（文件不存在 → 直接 empty，不调用 store
  读路径）；数据库已存在时经由 store 已批准的 `mode=ro` 读接口读取。
- 不修改快照、不自动修复损坏数据、不发起外部请求。
- 不使用系统当前时间改变业务结果。
- 不泄漏数据库路径、异常文本或 traceback。
- 普通存储异常失败关闭为 `status=error` envelope；KeyboardInterrupt /
  SystemExit / GeneratorExit 自然传播；未预期异常 → HTTP 502 稳定文案。

## 四、Data Health source

```text
source_id: bk11_history
module: BK-11 短线历史
display_name: BK-11 短线历史
detail_path: /daily-review
```

状态映射（直接只读检查 store，不表示任何外部数据供应商）：

| 存储状态 | record status | last_error_code |
|---|---|---|
| 数据库不存在 | unavailable | SOURCE_NOT_INITIALIZED |
| 数据库存在但无快照 | unavailable | SOURCE_NOT_INITIALIZED |
| 最新快照 normal | normal | — |
| 最新快照 partial | partial | SOURCE_PARTIAL |
| 最新快照 unavailable | unavailable | SOURCE_UNAVAILABLE |
| 存储损坏 / 读取失败 | unavailable | SOURCE_CORRUPTED |

`data_trade_date` 取最新快照业务日期；`observed_at` / `last_success_at` 取
快照自身时间；不使用系统时间伪造新鲜度（`is_stale` 恒为 False，不设置
stale 阈值）。

## 五、Daily Review 页面区块

- 独立组件：`frontend/src/components/dailyReview/ShortTermHistoryCard.tsx`
- view helper：`frontend/src/lib/bk11HistoryView.ts`
- 挂载点：`frontend/src/pages/DailyReview.tsx`（独立只读请求，仅挂载时一次；
  AbortController 防竞态；不随复盘轮询）
- 展示：最新快照日期/状态、核心市场事实、连板梯队、梯队断层、与前序快照
  变化、窗口摘要、确定性 digest、数据时间、limitations（技术详情可折叠）
- 空 / partial / unavailable / error 均视觉可区分；null 不显示为 0、
  不产生 NaN；digest 按纯文本渲染，无 HTML 注入；移动端无横向溢出；
  区块失败不影响页面其它区域。

## 六、测试

后端：

```text
test_bk11_history_service.py   （空库不建文件 / 多日 / 窗口边界 / 单日不伪造
                                 比较 / partial / unavailable / 损坏 fail-closed /
                                 只读 / 确定性 / 引用隔离 / KeyboardInterrupt）
test_bk11_history_api.py       （HTTP 200 envelope / 参数拒绝 / 损坏 200 error
                                 无泄漏 / 只读 / Data Health 联动）
test_data_health_adapters.py   （bk11_history 五态）
test_data_health_api.py        （registry 数量 14 → 15）
```

前端：

```text
tests/bk11HistoryView.test.ts   （格式化 / 状态标签 / delta / digest / null 安全）
tests/e2e/bk11-history-real.browser.mjs
  A 多日：事实/比较/摘要/digest、请求唯一、刷新轮询不重复、导航往返、
     Data Health 展示、移动端无溢出
  B 单日：不伪造比较
  C 空库：空状态、GET 不创建 DB、not_initialized
  D partial 明确展示
  E unavailable 不展示伪造指标
  F 损坏：区块失败、页面其余正常、无敏感泄漏
tests/e2e/data-health-real.browser.mjs（来源 ID/名称列表同步 +bk11_history）
```

实测结果：

```text
后端聚焦：81 passed
后端全量离线：3367 passed（基线 3336 + 31 新增），11 deselected，
             1 既有 warning（StarletteDeprecation），failed=0
前端单元：286 passed（+6）
前端 build：tsc -b && vite build 通过
BK-11 历史 E2E：6 场景全部通过
Data Health E2E：通过
py_compile：通过
```

## 七、非目标（本轮不包含）

```text
生产快照写入（受上游输入缺失阻塞，规则 C）
layered_promotion_rates
T+1 验证（Slice 4，受 Blocker 2 阻塞）
AI 复盘叙述
新外部数据源 / live 数据
Decision Evidence / Feedback / Analytics 接入
新页面 / 导航项
第二套数据库 / 第二套 Data Health 存储 / 新调度系统 / 新依赖
```

## 八、Blocker 状态（未变）

```text
Blocker 2：OPEN
Blocker 3：OPEN
Blocker 6：PARTIALLY CLOSED
layered_promotion_rates：未实现
```

## 九、已修改 / 新增文件

后端：

```text
backend/bk11_history_service.py        （新增，只读查询服务）
backend/bk11_history_router.py         （新增，HTTP 路由）
backend/app.py                         （注册路由）
backend/data_health_service.py         （SOURCE_REGISTRY +bk11_history）
backend/data_health_adapters.py        （Bk11HistoryAdapter + build_adapters）
backend/tests/test_bk11_history_service.py（新增）
backend/tests/test_bk11_history_api.py    （新增）
backend/tests/test_data_health_adapters.py（+bk11_history 五态）
backend/tests/test_data_health_api.py     （14 → 15）
```

前端：

```text
frontend/src/lib/api/types.ts              （Bk11HistoryEnvelope 等类型）
frontend/src/lib/api.ts                    （api.bk11History）
frontend/src/lib/bk11HistoryView.ts        （新增，view helper）
frontend/src/components/dailyReview/ShortTermHistoryCard.tsx（新增）
frontend/src/pages/DailyReview.tsx         （挂载区块）
frontend/tests/bk11HistoryView.test.ts     （新增）
frontend/tests/e2e/bk11-history-real.browser.mjs（新增）
frontend/tests/e2e/data-health-real.browser.mjs（来源列表同步）
frontend/package.json                      （test:e2e:bk11-history）
```

文档：

```text
docs/research/BK11_DAILY_REVIEW_HISTORY_V01.md（本文件）
docs/research/EXECUTION_STATE.md（状态行）
```

## 十、独立审查

待独立子代理审查（模型 opencode-go/deepseek-v4-flash）后在本文件与 PR
描述中记录结论。
