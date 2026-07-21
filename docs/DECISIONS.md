# 关键设计决定

格式：决定 → 原因 / 代码落点。事实均对应当前实现。

## 每日复盘

### 复盘页面允许 stale-while-revalidate

- **决定**：`GET /api/daily-review` 可在磁盘有最近成功包时立即返回 `stale=true`，后台 single-flight 刷新。
- **原因**：全 A 聚合冷路径约数十秒至两分钟，空白等待损害可用性。
- **落点**：`daily_review.get_daily_review_for_display`；提交 `2cf897c`。

### 持仓建议必须使用 fresh review

- **决定**：`portfolio_advice_service` 只调 `generate_daily_review()`，不用展示接口的 stale 包。
- **原因**：操作建议依赖当前广度与市场状态；陈旧复盘会导致错误仓位建议。
- **落点**：`app.py` 注释、`daily_review.py` 模块头、`test_daily_review_persist` 等。

### normal 不被坏 partial 覆盖

- **决定**：关键组件 unavailable 的 partial / 整体 unavailable 不覆盖已有 normal 内存或磁盘成功包。
- **原因**：短暂上游故障不应冲掉可用的完整复盘。
- **落点**：`generate_daily_review` / persist 规则；提交 `cf535b8`。

### 原始网络异常不得泄漏到客户端

- **决定**：对用户可见文案使用业务级错误；sanitize 公共字段；持仓建议 503/502 使用固定/安全文案。
- **原因**：避免 ProxyError、URL、traceback 进入页面。
- **落点**：`daily_review_errors`、`app.portfolio_advice`、`sanitize_review_public_fields`。

## 市场数据与网络

### 东财固定直连

- **决定**：`astock.em_get` 使用 `trust_env=False` 的 direct 会话，不走系统/环境代理。
- **原因**：代理导致国内行情域名 ProxyError / 中断分页。
- **落点**：`astock.py` 注释与 `_em_session` / `em_get`。

### 分页失败不返回半截市场数据

- **决定**：`a_share_snapshot` 在中途页失败时抛错，不返回已抓部分列表；不缓存 partial 快照。
- **原因**：半截全 A 会扭曲广度与成交统计。
- **落点**：`a_share_snapshot`；`test_astock_snapshot_paging`；`f2ae80c`。

### 本地 Clash Party（环境事实，非应用配置）

- **事实**：本机代理可对国内金融域名使用 DIRECT，境外模型/ChatGPT 仍走原代理策略。
- **不在仓库中记录**：订阅地址、节点密码、敏感配置。
- **应用层仍依赖代码直连东财**；代理仅为本机出站补充。

## 持仓建议

### breadth unavailable 时 fail-closed

- **决定**：广度组件 unavailable → 不调模型 → HTTP 503。
- **原因**：无可靠市场广度时的操作建议不可信。
- **落点**：`portfolio_advice_service` + `app.py`；`test_portfolio_advice_market_guard`。

### 操作比例使用固定档位

- **决定**：add 10/20；reduce 10/20/30；sell 100；其它动作 null；并受 confidence / partial 上限约束。
- **原因**：禁止模型任意百分比，便于审计与执行。
- **落点**：`portfolio_advice_validator` / prompt；`082e825`。

### add 数量由后端计算

- **决定**：`execution_quantity` / `estimated_amount` 由 validator 按持股与现价重算，覆盖模型结构字段。
- **原因**：模型不是执行字段权威；需 100 股取整与金额精度一致。
- **落点**：`5dec970`；`compute_add_execution_quantity` / `compute_estimated_amount`。

### add 比例表示相对当前持股

- **决定**：`execution_size_pct_of_holding` 语义为相对**该股当前持股数量**增减，不是账户总仓位/总资产/可用现金比例。
- **原因**：当前未接入总资产与可用现金，无法做账户仓位算法。
- **落点**：prompt 与 validator 账户比例话术拦截。

### 无历史 K 线不得编造技术位

- **决定**：上下文声明无 K 线/技术指标时，禁止支撑/压力/均线/N 日高低等无来源结论。
- **原因**：数据限制下的幻觉危害大。
- **落点**：`portfolio_advice_prompt` / 条件数字可追溯。

### 不做 T

- **决定**：第一版动作枚举无做 T；剥离 `t_trade` 结构。
- **原因**：无日内可卖/T+0 账户事实，且产品刻意收窄执行语义。
- **落点**：`afc6d73` 及后续 prompt/validator。

### 当前未接入账户总资产、可用现金和可靠可卖数量

- **决定**：`account_fields_available` 均为 false 量级；限制文案标准化；reduce/sell 提示人工确认可卖。
- **原因**：本地持仓 JSON 仅有股数与成本类字段，无券商实时接口。
- **落点**：context / validator 限制文案。
