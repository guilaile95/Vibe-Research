# Vibe-Research：全面产品、工程与开源对照审查

审查日期：2026-10-01（北京时间）。基线：本地 `712d0eaf6271e0951512958635894beab9331635`，与 PR #356 的 `295ef5ed39c0fed2bc2706deb1fd7a166e67cb9e` 同树。本报告包含本轮工作树修复；最终提交与测试状态以 PR 验收评论为准。

## 结论

这个项目已经不是一个缺少页面的行情网站，也不是尚未接入 AI 的空壳。它已经拥有市场发现、个股研究、资料检索、证据与投资逻辑、正式决策、持仓/成交、结果复盘的完整骨架。

目前的主要差距是：**拥有很多能力，却还不能稳定、简明地完成一次可信、可继续的研究任务。** 数据和 AI 的严谨程度因入口而异，产品对运行、数据、模型和任务状态的解释不够一致；本地存储与向模型发送的边界也需要更清楚。继续堆指标、模型、代理或数据源，收益可能低于把已有流程贯通。

建议定位为“可追溯的个人投研助手”：帮助提出问题、找证据、计算和比较、找反证、留下可检验的判断、到期回看。不要将当前描述性研究包装为已证明的赚钱策略，也不要为了这个定位重写已有正式账本。

## 审查方法及证据边界

本轮覆盖产品目标、信息架构、研究链路、数据语义、AI 能力、历史检验、持久化、安全隐私、性能、部署和测试，并阅读同类项目的具体实现。代码审查与合成复现用于证实行为；外部 README 只证明其宣称的能力，不证明质量优于本项目。

- 已执行：当前工作树检查、关键 source-to-sink 检查、合成数据解析/工具/模型载荷复现、前端处理器与状态测试、相关后端测试、前端全套测试与构建；外部项目只读调研
- 未执行：真实 API 模型质量评测、真实账户/持仓上传、真实数据源稳定性验收、当前云浏览器内的应用交互、目标干净 Windows 安装、长期使用价值实验
- CI 已有广泛浏览器测试，不能说“项目没有 E2E”。但其模拟 API 能证明交互契约，不能证明外部数据可靠或模型回答正确
- 这里是跨维度、重点路径的全面审查，不是逐行覆盖全部源码或已完成独立渗透测试的声明

## 一、能力盘点与产品取舍

| 用户目标 | 当前实际能力 | 判断及建议 |
|---|---|---|
| 找值得研究的标的 | TodayResearchLeads、Screener/Discovery、板块、Native Intel、自选异常 | 已有，不需要另起一个选股中心。把“为何出现、依据日期、缺什么、下一步核验什么”放在现有结果旁 |
| 研究一只股票 | StockData、相对强弱/估值、财报、事件、Ask AI、MyReports | 已有，问题在来源失败/空/旧数据解释不一致，应先统一证据质量 |
| 做完整研究 | 工具型 API Chat、多空辩论、页面型订阅 Chat、候选研究 | 能力分散。值得增加有界的“研究这个问题”任务入口，统一事实、推断、反证、未知和下一步，而非新增一个自由执行代理 |
| 留下思考 | 暂定研究、Notes、Evidence、Thesis 版本 | 保留轻量记录与正式事实的区别。AI 原文不能自动升级为用户已确认结论 |
| 下次继续 | researchResume、连续性摘要、日历、Campaign next-action | 已存在。优先连接最近保存的研究及其未决问题；不要再建一套历史库 |
| 处理持仓与复盘 | 正式决策、人工成交、归因/对账、FormalOutcome | 是重要差异化，应保留。减少用户被迫经过的表单，不削弱事实权威 |
| 第一次成功运行 | Windows 启动器、Runtime 状态、设置、Data Health | 缺清晰的首次成功路径与干净环境实测；配置保存成功不代表模型调用成功 |

导航有 10 个一级入口、约 35 个页面组件，且已有唯一导航配置和旧版工具分组。数量只能提示认知和维护成本，不能直接证明界面难用。建议先围绕“今天看什么 → 研究一只 → 留下结论 → 下次回看”优化默认路径；暂不删除正式能力或全面改版。

## 二、本轮确认并修复的问题

### 1. 资金流未知值及不完整窗口被当成完整事实

`astock.py` 的占位符原来转为 0；`ai_tools.py` 的两条观测也能产生标为 5/20/60 日的累计，并以 success、无 limitations 进入模型。使用真实函数和合成两行数据已复现。

修复：两条来源保留 null/真实零，保留有日期的截断行；累计要求相应观测条数、有效值和唯一有序日期，附 expected/observed/valid counts、partial 与局限。前端同步消费 nullable 字段。**足量观测仍不证明交易日连续性**，已经明确提示。

### 2. 研报/公告抓取失败被投影成“无资料”

StockData 把失败 catch 为 []，AI 上下文写“近期研报：无”。修复独立的 idle/loading/成功空/成功有值/error 状态；提供来源、日期、机构及链接，保留跨标的请求隔离。

### 3. 估值路径丢失报价日期

full_valuation 之前丢弃已取得的 data_time/trade_date。修复保留 quote_source/quote_data_time/quote_trade_date，并在工具和页面上下文展示。它们只描述报价，不代表财务、估值或盈利预测都同样新鲜。

### 4. 保存第 201 条研究记录会静默删除最旧记录

200 条上限是已有设计，不是新增回归。但原保存流程无提示淘汰用户研究和未决问题。修复为拒绝新增、提示导出并手动清理，原数据不变；显式删除后可重试。普通导入仍跳过超限新增项。异常超限存量不会被持久化/导入暗中裁掉，导出也不会伪装成完整的截断备份。

### 5. 多轮 AI 回答的保存来源与实际历史不一致

同一标的选择 A 后提问，再改选 B 追问，模型会沿用 A 的回答，但保存记录原来只有 B。修复将同标的完整历史轮次的来源一同保存，并明确标为历史轮次；当前来源优先，去重，不混入部分回答或其他股票。超过可存来源上限时，发送前提示保存并开始新对话，不静默截断。来源记录本身不代表模型已核验全文。

### 6. “持仓不上传”文案与模型调用不符

Portfolio 的持仓建议路径会将代码、数量、成本、市值、盈亏放进模型上下文（`portfolio_advice_context.py` → service → prompt → model runner）。原 legacy 提示却说不上传。

修复文案，生成前明确说明接收端、模型和数据类别，并询问是否继续；取消不启动模型任务。账户现金/总资产不在自动上下文内，但用户补充文字仍会发送。只用合成数据测试，没有传输真实持仓。这个前端确认不等于为全部 AI/API/MCP 调用增加了统一的服务端授权层。

## 三、全面审查发现的剩余问题

| 维度 | 已有优势 | 尚待处理／验证 | 优先级 |
|---|---|---|---|
| 数据一致性 | data_contracts 区分 effective/published/observed/fetched time；健康适配器只读 | legacy dict/list 消费路径未全部采用这些语义；StockData 多个次级数据请求仍隐藏失败 | 高 |
| AI 入口一致性 | Chat 有 partial/empty/error、合法 JSON 裁剪、工具状态 | Debate 把非空 partial 算 ok，并用原始字符串截断底稿；相同证据在不同入口含义不同 | 高 |
| AI 能力预期 | API 有受控工具；订阅 runtime 隔离、只看页面上下文 | 设置和按钮需明确“能否主动取数、能看哪些资料”；不要将订阅接入等同于自主研究 | 高 |
| AI 质量 | 有离线 grounding、检索/页码、validator golden cases | 没有可据此宣称真实回答质量的模型评测；应新增公开/合成问题集与证据标准答案 | 高 |
| 任务体验 | 多处有任务进度、取消、恢复和旧结果 | 缺统一的本次研究阶段与失败原因展示；先复用状态而非造任务平台 | 中高 |
| 数据保护 | 原子存储、损坏恢复、备份、正式数据本地存储 | 候选研究未保存草稿离开页面会丢失；浏览器记录与后端备份分离易漏备份 | 中高 |
| 隐私/安全 | Host/Origin/API key/non-loopback gates、PDF SSRF、CLI 安全测试 | `/api/margin` 等旧端点返回原始异常；已用合成异常复现。模型 key 在 localStorage，不能称为加密凭据库 | 高 |
| 性能 | market snapshot 已有 single-flight；Push2 预算/熔断；路由懒加载 | app._cached 同 key 并发冷请求未合并，双线程复现两次上游调用。真实 p50/p95 与 token 成本尚未测量 | 中 |
| 架构维护 | 正式权威模块分层，导航/政策有单一来源 | app.py/astock.py/StockData 大文件与新旧路径并存；应按修改热点逐步收敛，不按行数启动全量重构 | 中 |
| 历史检验 | factor/historical validation 显式 NOT_PROVEN、未复权/样本偏差说明 | current-only 工具不能回答历史时点事实；不得用今天数据支持过去决策或宣称策略收益有效 | 高 |
| 部署维护 | 两平台依赖锁、启动器、广泛 CI | 开发式三服务启动、无已验收的生产发布包；云环境预览阻断另属运行环境问题。打包无法自动解决该连接问题 | 高 |
| 文档 | 根 README/架构和限制文档较完整 | backend/README 仍说“全部只读、无状态”“MCP 四工具”，与演进后能力需重新核对 | 中 |

安全检查为关键路径审查及既有测试核验，不宣称已完成漏洞穷举。外部服务、模型成本、目标电脑安装、真实用户理解均有待专门测量。

## 四、开源项目具体对照

### 原上游 Vibe-Research

[阶段校验源码](https://github.com/simonlin1212/Vibe-Research/blob/main/orchestrator/src/finance/stage_validators.ts)会核对报价判定、权威冲突是否被覆盖以及反证引用 ID 是否真实。当前上游还区分普通直连与 Agent 研究。

值得借鉴：把“引用存在、引用对应什么、报价能否支持判断”变成可测约束，并明确不同接入方式的能力。不能直接替换我们的正式账本或整包套用六阶段编排；也不因此重开已延期的跨数据集发布门禁。

### daily_stock_analysis

已读 [HomeStockWorkspace](https://github.com/ZhuLinsen/daily_stock_analysis/blob/4e29abc636540420396f332dd2ad5555607791be/apps/dsa-web/src/components/watchlist/HomeStockWorkspace.tsx)、[ReportDiagnostics](https://github.com/ZhuLinsen/daily_stock_analysis/blob/4e29abc636540420396f332dd2ad5555607791be/apps/dsa-web/src/components/report/ReportDiagnostics.tsx)、[历史抽屉](https://github.com/ZhuLinsen/daily_stock_analysis/blob/4e29abc636540420396f332dd2ad5555607791be/apps/dsa-web/src/components/history/StockHistoryTrendDrawer.tsx)。

值得借鉴：自选股的上次分析/待分析/未知状态，本次 quote/daily/news/LLM/save 分段诊断，结果回看。其评分、买卖点或情绪历史不是我们的正式决策和结果权威，不原样照搬。

### ValueCell

已读 [任务结果卡](https://github.com/ValueCell-ai/valuecell/blob/9793e9c0563fbf56fc096757d8bb80e209ac7aab/frontend/src/app/home/components/agent-task-cards.tsx)和[任务控制器](https://github.com/ValueCell-ai/valuecell/blob/9793e9c0563fbf56fc096757d8bb80e209ac7aab/frontend/src/components/valuecell/renderer/scheduled-task-controller-renderer.tsx)。

值得借鉴：结果链接回原始研究会话、用户可见的取消。不能照抄把所有非运行状态都显示 Cancelled 的终态表达；其多代理架构也不是本项目必须迁移的目标。

### OpenBB

[Fetcher](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/abstract/fetcher.py)分离 query transform、extract、data transform；[AnnotatedResult](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/abstract/annotated_result.py)支持结果与附加元数据。

值得借鉴：让适配层保持明确的数据及错误契约。我们已有 data_contracts，无需为了接口分层新增另一套完整 provider 运行栈。

### TradingAgents

已读 [date_window.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/dataflows/date_window.py)和[trading_graph.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/trading_graph.py)：历史日期边界、屏蔽 live-only 资料、checkpoint 与配置变化隔离。

值得借鉴：时点一致性、任务恢复和配置 allowlist。不能把多代理的长篇讨论当成独立证据，更不应把其 trader/portfolio-manager 输出接成自动交易。其官方 README 也将其定位为研究框架，不保证固定可复现收益。

### FinRobot

已读[数字叙述检查](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/finrobot/engine/compute/operators/audit/narrative_numeric_grounding.py)。其计算/叙述分离方向值得参考，但该特定检查只是去掉年份、序数后检查是否仍有数字，源码明确不与实际数值白名单对照。

结论：借鉴“计算由代码做，模型负责解释”的原则；不能把“文中有数字”当作数字有据，不能直接以这种检查充当事实核验。

### Qlib 与 FinanceBench

[Qlib Recorder](https://github.com/microsoft/qlib/blob/main/qlib/workflow/recorder.py)提供参数、指标、产物、实验状态的追踪模式；[FinanceBench](https://github.com/patronus-ai/financebench)公开样本包含问题、标准答案、证据片段及页码。

值得借鉴：建立可重放的研究质量评测，而不是只测格式；A 股中文场景需另建适配题，不能用英语美股文档成绩直接推出本项目准确率。不必引入整个 Qlib/MLflow，也不直接复用早期模型失败率评价今天的模型。

### AKShare、pandas 与 Joplin

[AKShare 资金流解析](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_fund_em.py)使用 coercion 保留无效数值语义；[pandas nanops](https://github.com/pandas-dev/pandas/blob/main/pandas/core/nanops.py)有 min_count 聚合门槛。它们支持本轮“未知不是零、样本不足不冒充完整”的改进，但提供方 DataFrame 本身不证明时效及完整性。

[Joplin 历史机制](https://github.com/laurent22/joplin/blob/dev/readme/dev/spec/history.md)区分当前笔记与有保留期的修订。应借鉴用户研究不可静默淘汰的保护思路；本轮不引入同步或全量版本系统。

### Ghostfolio

已读[活动导入对话框](https://github.com/ghostfolio/ghostfolio/blob/05459aaa3588ad1b1d89d178c993b2516cb604cd/apps/client/src/app/pages/portfolio/activities/import-activities-dialog/import-activities-dialog.component.ts)：dry-run、逐行错误、选择后提交。

后续若人工成交录入成为主要负担，可以借鉴“先预览再导入”。必须维持本项目的 attribution/reconciliation 和人工确认，不接入下单，也不替换整个账本。

## 五、建议的改进顺序与验收

### 第一层：可信、能用、不会丢

1. 完成本轮证据/来源/记录/隐私修复并回归
2. 统一剩余旧入口的失败和 partial 表达，特别是 Debate 与 StockData 次级数据
3. 脱敏旧 API 原始异常；检查所有敏感上下文出口的用户说明
4. 在真正可用的目标运行环境建立首次成功路径：启动服务、查看有时间的数据、确认模型可用、保存一条研究、重启找回

验收：缺失数据不变成零/无记录；没有确认不启动持仓模型请求；满容量不删旧记录；来源随完整历史一致；重启可找回。实际云预览和真人模型验证单独列结果，不用 CI 代替。

### 第二层：让 AI 真正完成一项研究

在已有 Candidate / Ask AI / MyReports 上形成一个有界任务：明确研究问题 → 选择/读取证据 → 代码计算 → 正反论据 → 不确定项 → 用户保存与下一步。展示哪些资料已读、哪些工具没取到、当前阶段及取消；不新增正式事实写入权。

验收题应包含：最新与过期报价、营收增长但现金流下降、两个来源冲突、未入模报告、完全缺数据、资料内含恶意指令、跨标的追问、工具超时、取消后重试。记录数字一致性、引用支持率、未知表达、重复/无用结论、耗时和调用成本。真实模型运行需用户在支持的入口自行配置凭据，样本不含私人账户数据。

### 第三层：降低日常使用成本

复用现有首页/自选/连续性功能，给出“上次研究什么、后来发生什么、今天最值得核对什么”，并能回到原记录。加入候选未保存草稿保护，统一备份说明。先测真实页面跨度和首次成功时间，再决定是否合并导航；不把“10 个菜单”自动判成需要大改。

### 第四层：有证据再加高级能力

真实需求成立后，再考虑可配置的关注事件、成交导入预览、更强研报检索、PIT 数据和规范回测、受控只读研究工具在不同模型接入间的能力对齐。每项必须说明覆盖范围、成本/额度、失败语义与验收标准。

## 六、明确不建议的方向

- 不整体重写为 TradingAgents/FinRobot/ValueCell；保留有效的正式事实、决策与结果边界
- 不同时增加多个 provider、多个 Agent 框架、第二个历史库或未经测量的向量检索
- 不根据回测界面、测试数量或一次漂亮回答宣称投资效果已证明
- 不为提高速度并发轰击受限免费源，也不隐藏错误以制造流畅
- 不把便携软件、云服务器、模型接入混为一个问题：安装依赖、网络可达、持续运行、模型授权是四个分别需要验证的条件

## 七、最终判断

保留项目已有的研究与决策骨架，收敛数据及 AI 的不一致，建立可衡量的研究任务体验。真正值得补的核心能力是“有依据的完整研究及后续追踪”，而不是再多一页图表。这个方向可以逐步实现，不需要推倒重来；但其真实价值仍需实际使用验证，本报告没有代替那一步。

## 本轮本地验证记录

- 前端全套：809 passed；TypeScript/Vite 生产构建通过（既有图表 chunk >500kB 提示仍在）
- 后端全套离线：8,350 passed，2 failed，8 skipped，12 deselected。失败为现有环境下多进程 Manager/IPC 与 SOCKS 依赖不可用；没有将这次结果称为全绿
- 后端资金流/估值等相关回归：253 passed；补充文案后 focused 75 passed
- 原本已有的 factor/history/cache/health/AI-result/report 契约检查：101 passed
- 持仓发送确认：取消不调用、确认才调用、未知接收端失败关闭及 URL 凭据不进入确认文本的合成处理器测试通过
- 已更新两条相关浏览器用例以显式处理模型发送确认，尚待当前提交的 CI 验证；本地没有绕过云浏览器限制运行另一浏览器验收

这些数字只描述代码契约，不证明真实模型质量、投资收益或长期服务可用性。最终远端 exact-head CI 以 PR 评论链接为准。

## 审查后的继续完善

根据用户继续推进的要求，本报告之后又完成以下有界修复；上文剩余问题表是审查当时的发现，以下更新覆盖相应条目：

- StockData 的 12 类次级数据（资金流、两融、股东、分红、大宗、龙虎榜、解禁、板块、热门概念、问答、新闻、历史分位）现在区分加载、接口返回空、失败和 501 不支持。独立请求保留跨标的隔离，避免新闻/分位阻塞主行情。接口若已经把上游失败吞成 HTTP 200 空列表，前端仍无法还原原因，因此文案不声称现实中不存在记录
- Debate 复用 Chat 的合法 JSON 有界序列化，保留真实零，明确 partial/stale/truncated；可用的部分证据继续入模，与完全缺失分列。进度与界面保留相同含义，主持阶段也遵守证据约束
- app.py 中 49 处一般 502 错误响应采用固定业务提示，不返回异常原文或内部异常类型。保留 HTTP 状态、已分类的业务错误和 fail-closed 行为；这不是对所有模块所有错误出口完成穷举的声明
- Settings 增加可展开的首次研究状态：浏览器配置、后台凭据、尚未验证模型、实际保存记录数量及损坏状态；说明 API、Codex、旧 CLI 的能力差别。复用现有后端运行信息，保存提示不再暗示模型已验证。没有偷偷新增模型调用或“连接已通过”的假状态

新的浏览器 fixture 覆盖次级来源 502/501 后的状态及恢复为空结果，等待该提交 CI 运行。前端全套 826 项通过及生产构建通过；后端、远端 exact-head 验证见本批最终 PR 评论。

尚待推进：首次模型连接的严格限时/限输出测试、真正的研究质量评测、未保存草稿保护、减少重复上游请求、在实际可用环境完成首条研究。它们没有被本次界面状态完善冒充为完成。

续修最终本地后端回归：8,385 passed、2 个已知环境失败、8 skipped、12 deselected。首轮还发现两条旧测试要求公开异常原文，以及 Holding 失败提示丢失有用分类；已改为验证安全固定提示，并保留“权威不可读”的业务含义。相关 51 项及最后全量复测已确认该三项不再失败。独立跨文件复查未发现阻断回归；远端 CI 尚待发布后验证。

## 手动模型连接检测落地

后续实现了[独立的有界 API 连接检测](../AI_CONNECTION_TEST.md)：当前表单值、手动点击、固定合成句、单次无工具请求、15 秒等待预算、请求 32 token 输出、字节/行/文本上限、断连取消，以及配置变化后旧结果失效。结果不保存，不读取或发送私人研究资料，不支持 CLI 探测，也不将成功等同于模型研究质量。

独立复查发现并修复了浏览器与后端对特殊 URL 解析不同导致的接收端披露不一致；原例并未证明 API Key 泄露，不作此推断。现在提交与展示使用同一规范化 URL，服务端预检也拒绝含混地址。另补 CR-only SSE 支持。所有验证均为合成样例。

上一批 Windows CI 的唯一失败是新增源码检查未指定 UTF-8，在 CP1252 环境下读取中文失败；已补显式编码并通过本地 18 项相关测试。上一批不能标记为全绿；新提交须重新验证该 Windows 项。

连接检测本地最终验证：前端 836 项通过且生产构建通过；后端全量离线 8,450 passed、2 个既有环境失败、8 skipped、12 deselected。地址校验修复后的相关 125 项通过；UTF-8 修正的 18 项通过。独立复查确认接收端一致性与 CR-only 问题关闭；真实端点、真实模型质量和该提交的远端 CI 仍须分别验证。
