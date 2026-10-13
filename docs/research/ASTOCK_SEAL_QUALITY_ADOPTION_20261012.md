# AStock 封板质量采用：只读计算基础

日期：2026-10-12。第一切片为纯计算基础；后续同日新增只读归档API和组件接线（见文末）。
**生产采集未启用；真实市场来源和浏览器端到端验收不能由本地离线测试替代。**

## 采用目标和边界

参考固定 upstream `simonlin1212/vibe-astock@d5bf80d2ed1629f8fa602058093f8d41bb0c7ace` 的
[seal_quality 观察维度](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/.agents/skills/data-access/scripts/sources/shortline_facts.py)。
本实现独立编写，复用当前 `short_term_limit_up_pool_adapter` 的字节解释和来源准入。

本次不改既有 adapter 行合同、final producer、canonical fact/hash、历史快照、
分层晋级 coverage gate、交易日历、交易/持仓写入；不新增 provider 请求。
封板质量不能仅凭现有 `stock_code/lbc/zt_stat` 还原，必须读取同一捕获响应的实际字段。

## 输入输出合同

入口：`short_term_seal_quality.build_seal_quality_observation`。

输入：exact raw response bytes、requested_trade_date、http_status、observed_at。
observed_at 必须是有时区的显式捕获时间；它不是来源日期证据，也不证明收盘定稿。
既有 adapter 必须独立确认 payload 日期，且返回 normal、无代码/覆盖歧义。
日期缺失/冲突、部分来源、重复代码、HTTP 错误、不可解释空池均不能获得指标。

输出 `RESEARCH_OBSERVATION`：

- 计算 exact raw SHA-256，保留捕获时间及 adapter 来源状态；hash 只识别内容，不声称它已经提交到快照库
- `finality=NOT_ESTABLISHED`、`canonical_authority=false`；盘中或盘后调用都不自动升级 authority
- 目标 universe 沿用既有 adapter（沪深主板、创业板、科创板），另报排除样本数
- 逐行保留 lbc 和原有 N/M 格式 zt_stat，不替换连续板高度
- fbt/lbt → first_seal/last_seal：HHMMSS 上海时间，09:25–11:30 或13:00–15:00，且不晚于捕获时间
- 整数时间允许补前导零；任意浮点、boolean、非法格式、非交易时段时间不猜测
- 末封早于首封：两字段均 unknown；不会交换或改写来源值
- zbc → broken_times：严格非负32位整数；缺失、字符串、浮点、boolean、负数、越界均 unknown
- 每行有 field_issues；每字段有 known/unknown 数量，只有全样本字段覆盖时才算相关聚合
- 比例为0–1小数，次数/样本数量分开；不搬运价格和收益，不引入百分点与比值、千分价格转换歧义

指标：从未开板数量/比例、开过板数量/比例、平均开板次数、09:35及以前首封数量、14:30及以后末封数量。
09:35与14:30是显式本地描述性阈值，含边界，前者含集合竞价；不是交易所权威分类或策略推荐。
涨停股盘中开板比例不等于全市场炸板率，后者需要另一个炸板池分母，本次不输出。

旧捕获没有这些字段时，旧梯队能力仍有效，新质量指标为 unavailable；不回填、不填零。
一个字段缺失不掩盖其他字段：逐项覆盖不足则该项为 null，允许 partial 结果。
normal 仅表示该次来源样本相关字段完整，不能证明全市场完整性、收益或可成交性。

## 验收矩阵

| 类别 | 断言 |
|---|---|
| 正常样本 | 完整逐行字段、聚合值、覆盖计数、来源绑定和 raw hash |
| 真零与缺失 | zbc=0有效；缺失、非法值不变成0，不缩小分母后伪称总体比例 |
| 时间 | 首末顺序、午休/越界、盘中未来值、带时区捕获、阈值边界 |
| 来源 | 日期缺失/跨日、HTTP 403/429、无效JSON、重复JSON键、重复代码均失败关闭 |
| Universe | 北交所样本不混入目标分母；过滤后空样本不可评估 |
| 兼容性 | 原有N/M、lbc与adapter返回保持不变，不借用价格或收益单位 |
| 纯计算 | 无网络、DNS、clock/calendar查询、文件I/O；同输入同输出 |
| Authority | 不产出final、canonical、晋级率、交易信号或收益 |

2026-10-12 聚焦验证：新增 seal-quality 测试、已有 limit-up adapter、final-snapshot、
committed-raw replay、layered-promotion coverage-gate 共 **606 passed**。
测试使用临时数据目录及禁网/DNS guard，guard记录0次 socket/DNS 尝试。
未运行全量后端、浏览器、真实模型或行情请求；不能据此宣称真实来源或用户界面已验收。

## 后续接线合同

独立审查通过本计算合同后，复用可信已存储 raw observation 的读取与身份校验入口，
将该只读投影接入现有短线详情/API和界面，显示 capture identity、来源日期、覆盖和缺失原因。
不能让界面自行填写 observed_at/date 以冒充可信历史记录；也不能为GET暗中补抓或写数据。
此合同已实现下面的候选接线；默认采集和自动历史补全仍未实施。

昨日强势股反馈矩阵尚未实施：先具备昨日股票池、当日收益与交易日绑定、缺失样本分母，
再做结果分组；不能因为已有 coverage eligibility gate 就宣称晋级率已获准。

## 同日只读归档API与组件接线候选

- `GET /api/market/seal-quality?trade_date=YYYY-MM-DD`：只接受一个日期参数，拒绝路径、as_of、捕获时间或自选选择策略
- 仅打开已经显式配置的 `VR_FACT_LAKE_ROOT`，调用 `open_existing_fact_lake(..., readonly=True)`；不创建、迁移或启用 shadow ingestion
- 使用公开 `list_canonical_publications` 精确查询日期，沿用 Q1 `LOCAL_LATEST`；只是本地发布序，不声称供应商最后修订或历史当时可知
- 对所选 publication 绑定的 observation 执行既有 `verify_normalization_replay`，核对 committed receipt、来源路由、日期、raw hash、normalizer、canonical payload
- 只有通过上述身份链的原始字节进入纯计算；不允许客户端填写观测时间替代存档证据
- 无配置显示 `ARCHIVE_NOT_CONNECTED`；无此日发布显示 `ARCHIVE_OBSERVATION_MISSING`；旧存档缺字段显示 `QUALITY_FIELDS_INCOMPLETE`
- manifest/版本/哈希/路径或symlink异常失败关闭，响应不回显路径、原始载荷或异常文本；整个GET保持归档树字节不变
- `DailyReview` 的当前复盘区域和已选历史详情分别传入自己的交易日，未确定日期时不请求；组件代际、AbortSignal与render-date gate共同隔离迟到响应
- UI显示逐项覆盖、缺失为“—”、比例单位、源日期/捕获时间/发布与观测身份、本地选择语义、非定稿/非炸板率边界

新增 **26项**真实临时归档→已注册HTTP路由测试通过，包含访问密钥/Origin边界、GET字节不变、缺root不创建、错误日期/参数、损坏与版本、symlink和迟到数据前提。
新增 **5项**前端readback/fixture合同测试通过；TypeScript、生产构建与组件adapter build-only通过。

独立浏览器脚本：`frontend/tests/e2e/seal-quality.browser.mjs`，1440/390各6个场景，
包括完整/部分/未连接、已取消但仍被解析的旧响应、错误日期、空日期/卸载重挂。
它复用真实生产组件及API client，使用合成日期父组件和精确只读fixture响应，**不启动任何后端/供应商进程**。
这是组件级证据，不能冒称完整DailyReview页面或真实市场已验证。

本地仅运行 `--build-only`，浏览器 **NOT_RUN**；必须由已授权CI实际调用无该flag的脚本并检查result.json与截图后，才能记录浏览器通过。
输出目录由 `SEAL_QUALITY_BROWSER_OUTPUT_DIR` 指定；fixture脚本拒绝非本origin请求、WebSocket、非白名单API及非GET。
