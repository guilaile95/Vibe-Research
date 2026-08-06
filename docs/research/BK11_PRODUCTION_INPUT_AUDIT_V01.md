# BK-11 生产快照上游输入来源审计 v0.1

| 项 | 值 |
|----|-----|
| 阶段 | bk11-production-ingestion-v0.1（来源合同审计） |
| 分支 | feat/bk11-production-ingestion-v0.1 |
| Base | 12593c340845a60b70c925bdceb7265b5710511d（feature/research-system-v01） |
| 审计日期 | 2026-08-06（Asia/Shanghai 探测） |
| 结果 | **路径 C：BLOCKED**（合法完成结果，等待用户决定来源策略） |

## 一、目标与范围

为 `compute_daily_facts` 的四类输入（final_snapshot / breadth /
limit_activity / facts_data_health）建立可信生产来源，并决定是否实现
生产写入。审计遵循任务硬门：不得猜测字段、补零、混用日期或把当前行情
冒充历史行情。

## 二、已批准能力现状（复用，不复制）

```text
short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot(date)  # 涨停池适配器
short_term_limit_up_final_snapshot.fetch_final_limit_up_pool_snapshot(date)  # 三次稳定观测 producer
short_term_daily_facts.compute_daily_facts({final_snapshot, breadth, limit_activity, facts_data_health})
short_term_fact_store.save_daily_facts(envelope)
bk11_history_service / bk11_history_router / Data Health bk11_history / Daily Review 历史区块
```

生产代码当前没有任何调用方生成 final_snapshot / breadth / limit_activity /
facts_data_health 并写入 store（既有审计结论，本任务重新确认：`rg` 显示
上述 producer/save 函数仅有模块定义与测试引用）。

## 三、来源合同矩阵

### 3.1 市场宽度（advance_count / decline_count / flat_count /
suspended_count / eligible_count）

候选来源：东方财富 push2 `clist/get` 全 A 快照（`astock.a_share_snapshot`，
经 `astock.em_get` 统一限流）。

| 维度 | 证据 |
|---|---|
| 生产函数 | `astock.a_share_snapshot()`（无日期参数）；`market.calculate_market_breadth()` 纯计算 |
| 原始字段 | `f3`(涨跌幅) / `f2`(价格) / `f12`(代码) / `f14`(名称) 等 |
| 数据提供方 | 东方财富（Tier B 商业源，无公开 API 文档，许可 unclear） |
| 显式 requested_trade_date | **无**：`clist/get` 只返回当前快照，不接受历史日期 |
| 响应是否返回实际交易日期 | **无日期字段**；`market._breadth_envelope` 的 `trade_date`/`data_time` 恒为 None，且恒带警告 `_WARN_NO_TRADE_META`（"源数据未提供明确交易日期和行情时间"） |
| 合法零值与接口异常区分 | 不可区分：空快照与字段缺失均只能转 unavailable；合法 0（如平盘数）依赖字段存在性 |
| 最近非空交易日回退 | 无显式回退；但源本身代表"当前状态"，捕获时点决定归属 |
| 缓存 | `market.get_market_breadth()` 有 5 分钟内存缓存；缓存不带交易日期 |
| 空值语义 | `change_pct` 缺失（`'-'` → None）；存在停牌/缺字段/解析失败/覆盖不完整四种可能，无法区分 |
| 覆盖率语义 | `stock_count` / `valid_count` / 字段有效比例（partial 阈值 3000 只 / 80%） |
| 失败关闭 | `get_market_breadth` 捕获异常转 unavailable envelope；不伪造全 0 |
| 凭据 | 无账号/Cookie/Token/付费 |
| 满足 BK-11 合同 | **不满足**：breadth 原始字段需要 `suspended_count` 与 `eligible_count`，而快照无停牌状态标记字段 |

### 3.2 涨跌停活动（limit_up_count / limit_down_count /
failed_limit_up_count）

候选来源：东方财富 push2ex 涨停板四池（`astock.em_zt_topic_pool`）。

| 维度 | 证据 |
|---|---|
| 生产函数 | `astock.em_zt_topic_pool(endpoint, date, sort)`；已批准 `short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot(requested_trade_date)` |
| 原始字段 | 池行 `c`(代码) / `lbc`(连板) / `p`(价) 等；计数=池行数 |
| 数据提供方 | 东方财富（Tier B） |
| 显式 requested_trade_date | **有**（YYYYMMDD 请求参数） |
| 响应是否返回实际交易日期 | 行内无日期字段；adapter 对 payload data 层执行 `trade_date_match` 校验，无法校验时返回 `DATE_BINDING_UNVERIFIED` |
| 合法零值与接口异常区分 | **不可区分**：已批准 adapter 的 `legal_zero` 恒为 False（无可信 final 证据证明当日全市场无涨停），空数组不得认定为合法 0 |
| 最近非空交易日回退 | `market._emotion()` 会向前回溯 8 天取最近非空涨停池——**该回退路径不可用于严格指定日期生产输入**（本任务确认） |
| 缓存 | `market._cached("emotion", ...)` 5 分钟；缓存不带捕获日期 |
| 空值语义 | 空池 = UNEXPLAINED_EMPTY / legal_zero=False，不解释为 0 |
| 覆盖率语义 | `source_pool_row_count` / `excluded_universe_count` 等适配器字段 |
| 失败关闭 | adapter 十字段合同，失败关闭，无泄漏 |
| 凭据 | 无 |
| 满足 BK-11 合同 | **部分满足**：正数日可行（显式日期 + 失败关闭）；**0 值日无法生产**（legal-zero 未证明） |

### 3.3 Data Health（transport_success 等）

可由输入适配器按现有 adapter 合同构造（与 `_DATA_HEALTH_BOOL_FIELDS` 对齐），
不构成阻塞。

## 四、有限探测证据（2026-08-06，临时目录 C:\tmp\bk11-probe，
未写真实数据库，未提交原始数据）

### 4.1 push2ex 涨停池（显式历史日期）

```text
getTopicZTPool(20260806) → 45 行；行字段含 c/n/lbc/p/zdp/fbt/lbt/amount 等；
行内无日期字段（日期绑定依赖请求参数 + adapter 校验）
```

可达性：✅ 成功。正数涨停日的显式日期请求可行。

### 4.2 push2 clist/get 全 A 快照（市场宽度候选）

```text
全量分页（astock.a_share_snapshot）：第 22 页起 RemoteDisconnected（连接被
远端关闭），重试失败；
等待 60 秒后单页请求成功：total = 5891，页面行无日期字段；
随后再次连续 3 次请求全部 ConnectionError（限流/断连），30 秒间隔重试无效。
```

运输层结论：**当前网络环境下 clist/get 全量采集极不稳定**，59 页级全量
采集无法保证完成；限流恢复时间不可控。此证据同时说明：

- 收盘捕获（路径 B）依赖的全量快照抓取在生产上不可靠；
- 无法在当前环境完成 suspended 语义的完整交叉验证。

### 4.3 停牌语义

`clist/get` 字段集中**没有停牌状态标记字段**（f2/f3/f5/f6 缺失仅表示
"无值"）。缺失 `change_pct` 的行可能是停牌、缺字段、解析失败或覆盖不
完整（任务第 9/10 条）。候选交叉验证源（腾讯 gtimg）同样是"价格缺失"
推断，无法提供交易所状态证明；且网络同样不稳定。**无证据证明"所有缺失
change_pct 均表示停牌"**。

## 五、硬门逐条判定

| 接受标准 | 判定 |
|---|---|
| 1. 交易日期通过源响应或可信捕获时点明确绑定 | ✗ breadth 源无日期字段/无日期参数；捕获时点绑定仅靠墙钟推断，且源全量采集不稳定 |
| 2. 不得把 T+1 当前行情标为 T 日数据 | 可遵守（路径 B 设计），但源无日期字段使验证只能靠捕获时点 |
| 3. 不得混合 T 日涨停池与 T+1 市场广度 | 可遵守，但 breadth 日期无法从源验证 |
| 4. 不得把"最近非空交易日"当作请求日 | `market._emotion()` 的回退路径已确认不可用于生产输入 |
| 5. 不得把接口空列表解释为合法 0 | ✗ 涨跌停 legal-zero 未证明（已批准 adapter 恒 False）；0 值日不可生产 |
| 6. 不得用历史页面显示值反推 | 可遵守 |
| 7. 不得用 AI 文本/页面文案/digest 作来源 | 可遵守 |
| 8. 不得用 fixture/测试数据/手工常量 | 可遵守 |
| 9. 不得把无效 change_pct 全部认定为停牌 | ✗ 无停牌标记字段，语义未证明 |
| 10. suspended_count 不得简单设为 stock_count - valid_count | ✗ 无上游合同或响应证据证明缺失==停牌 |
| 11. eligible_count 必须有明确口径 | △ clist total=5891 可作为候选口径（东财 fs 全 A 集合），但与 breadth_universe 一致性无合同验证，且依赖不稳定源 |
| 12. source date/capture date/business trade date 分别记录 | 可遵守（设计层面） |

## 六、路径判定

```text
路径 A（直接历史采集）：不成立 —— breadth 源无历史日期参数，无法按
requested_trade_date 获取明确日期绑定的市场宽度。

路径 B（收盘捕获 + 次日终结）：不成立 ——
  1. suspended_count 无可信来源（无停牌标记字段，缺失即停牌未证明）；
  2. eligible_count 口径依赖单一商业源且未完成一致性验证；
  3. 全量快照采集在当前网络环境反复断连（22 页断连、恢复后再次断连），
     收盘捕获的生产可靠性无法保证；
  4. 涨跌停 legal-zero 未证明，0 值交易日无法生产；
  5. breadth 源无日期字段，日期绑定只能依赖捕获时点墙钟推断。

路径 C（BLOCKED）：成立 —— 满足 BLOCKED 触发条件：
  - suspended_count 没有可信来源；
  - 无法证明 breadth 与目标交易日一致（源无日期，捕获不稳定）；
  - 无法区分合法 0 与接口异常（legal-zero 未证明）；
  - 网络探测显示关键源运输层不稳定。
```

**结论：路径 C（BLOCKED）。不实现生产写入，不修改页面为已有生产能力。**

## 七、缺失字段与候选解决方案（供用户决策）

| 缺失/阻塞项 | 候选解决方案 | 代价/风险 |
|---|---|---|
| suspended_count 可信语义 | 交易所停牌列表（上交所/深交所官网公告或数据接口，Tier A） | 需新增官方数据源与解析器；免费但需接入工作 |
| breadth 显式日期绑定 | 交易所/官方历史行情（Tier A）；或商业化历史快照 API（付费） | 付费或接入成本 |
| legal-zero（0 值日） | 官方收盘统计（涨停家数 0 的权威确认）；或接受 0 值日不可生产 | 合同变更需重新审查 |
| eligible_count 权威口径 | 交易所挂牌总数 / 官方统计口径 | 需合同验证 |
| 全量快照运输稳定性 | 官方批量行情接口；本地行情缓存服务；或降低频率 | 架构/成本 |

## 八、本轮未实现（明确声明）

```text
未实现生产写入（无 bk11_ingestion_service / router / input adapter / staging）；
未修改 short_term_daily_facts 的 "production integration not authorized" 文案；
未修改 bk11_history_service 的阻塞文案；
未修改 Daily Review 空状态文案；
未新增数据源、未付费、未使用凭据、未写真实 short_term_facts.sqlite3；
未实现 layered_promotion_rates / Slice 4 / 回填 / 调度。
```

## 九、既有文案状态

因结果为 BLOCKED，任务第十二节要求的过时文案同步**不执行**：阻塞说明
（`production integration not authorized` / `生产快照写入仍受上游输入
缺失阻塞`）保持原状，与事实一致。
