# 上游吸收调查 — 2026-09-26

本文记录本次调查的不可变比较坐标、来源证据和吸收决定，不维护任务分支、运行 SHA 或实时工程状态。下列适配范围以本补丁实现为准；合并与 CI 状态查对应 PR，不由本文充当实时状态表。历史文档保留原样；实际交付以对应代码、PR 和验证证据为准。

## 已核实来源与比较基准

| 来源 | 最后可证实的吸收基准 / 方式 | 本次核验上游 HEAD | 差异与证据 |
| --- | --- | --- | --- |
| [simonlin1212/Vibe-Research](https://github.com/simonlin1212/Vibe-Research) | `b65ad42d02e5adc45d494a842c50afe4d79d2fe9`；[#262](https://github.com/guilaile95/Vibe-Research/pull/262)、[#263](https://github.com/guilaile95/Vibe-Research/pull/263)、[#264](https://github.com/guilaile95/Vibe-Research/pull/264) 于 9 月 2 日合并页面聊天、研报检索、研究连续性适配 | `85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3` | [比较](https://github.com/simonlin1212/Vibe-Research/compare/b65ad42d02e5adc45d494a842c50afe4d79d2fe9...85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3)：新增 33 个提交；最新 release v1.2.0。有研报覆盖、AI 接入、新闻取数等增量，不整体合仓。 |
| [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) | `8ee26026ba6c11dec41a95fb3895a7162876caa1`，v6.10.0；Native Intel 独立行为实现，见 [对齐矩阵](../TRENDRADAR_PARITY_MATRIX.md) 和 Wave 4/5 合同 | `792bcc3928b1617bba09df34989fd5675c159b86` | [比较](https://github.com/sansan0/TrendRadar/compare/8ee26026ba6c11dec41a95fb3895a7162876caa1...792bcc3928b1617bba09df34989fd5675c159b86)：2 个提交、2 个 README 文件，`DOCS_ONLY`；无新增运行能力。Wave 6/7 是既有计划。不得复制 GPL 实现。 |
| [simonlin1212/vibe-astock](https://github.com/simonlin1212/vibe-astock) | `d3af182b43aa75a5604ee467794ef7cfc70d1c01`；[#202](https://github.com/guilaile95/Vibe-Research/pull/202) 于 8 月 23 日吸收精确板高、N天M板及有效高度语义。初始调研 `f4030751b612acb2a017135345005b7befb919e9` 已不是最后吸收基准 | `bd96df4045e7a4a68478862d18358139599fcf34` | [比较](https://github.com/simonlin1212/vibe-astock/compare/d3af182b43aa75a5604ee467794ef7cfc70d1c01...bd96df4045e7a4a68478862d18358139599fcf34)：新增 33 个提交；最新 release v1.1.3。局部适配校验思想，不引入第二套运行时、存储或路由。 |
| [rootSunc/ashare-lake → CNEquity](https://github.com/rootSunc/CNEquity) | v0.7.2 / `a18ee0484dfb0801650175471724def3228b8a17`；同一 #202 吸收 sparse/session_dense 与连续交易日安全水位。早期架构评审基准为 `a2713c26d0b2ea84b2721d93788fb83be7feac95` | `1650e384a3fd1f67a70144a489acc91432f1df27` | [v0.11.0](https://github.com/rootSunc/CNEquity/releases/tag/v0.11.0)新增标的截面覆盖等能力。旧提交可读取，但[比较请求](https://github.com/rootSunc/CNEquity/compare/a18ee0484dfb0801650175471724def3228b8a17...1650e384a3fd1f67a70144a489acc91432f1df27)返回 `No common ancestor`；线性提交增量及原因 `UNKNOWN`，改以固定提交源码和发布记录核验。 |
| [ourongxing/newsnow → newsnext/newsnow](https://github.com/newsnext/newsnow) | 公共 HTTP API 接入，非代码吸收；矩阵记录 9 月 3 日接口核验。历史代码 SHA / 服务部署版本未锁定 | `0f95b2c998dffbfd2ddbc51b47b5809887dc6b97` | [v0.0.42](https://github.com/newsnext/newsnow/releases/tag/v0.0.42)、[发布差异](https://github.com/newsnext/newsnow/compare/v0.0.41...v0.0.42)含部分资讯来源及 PWA 修复；版本比较不等于本项目吸收差异。公共实例实际服务版本 `UNKNOWN`，不由仓库 HEAD 推断。 |

#202 的实际吸收与贯通范围见 [UPSYNC1 最终验收记录](https://github.com/guilaile95/Vibe-Research/issues/200#issuecomment-5383291280)。早期 VIBE_ASTOCK_ADOPTION_PLAN / ASHARE_LAKE_SEMANTIC_GAP_REVIEW 的暂停或旧基准表述仅作为历史证据，不覆盖后续已合并记录。候选项目、被拒绝的架构参考、普通依赖和 Skill 库存不计为已吸收来源。

## 本轮适配的两个目标

| 目标 | 实现方式 | 复用证据与边界 |
| --- | --- | --- |
| 研报问答覆盖完整性 | 独立适配 | 参考原 Vibe [`952497c`](https://github.com/simonlin1212/Vibe-Research/commit/952497c8830ba12036b4d471b206f9a4c30fdfeb) 的选中资料覆盖与截断提示。沿用既有 MyReports / Ask AI / 显式 report_ids，区分所选报告与实际进入上下文的报告，披露未覆盖情况；不把页命中数当报告覆盖数，不扩大到自动全库召回。 |
| Native Intel 严格 JSON 解析与有界修复 | 独立适配 | 参考 vibe-astock [`d7a0e568`](https://github.com/simonlin1212/vibe-astock/commit/d7a0e568424f5c0b1de9e39b1ddd733ecdbf9edb) 的严格完整 JSON 信封、重复键拒绝和受限纠错。适配既有 Native Intel schema 与一次 repair 边界，不导入其复盘 schema、不猜测 Evidence ID、不增加无限重试；若复制代码须保留 Apache-2.0 归属。 |

CNEquity 的[标的截面核验](https://github.com/rootSunc/CNEquity/commit/66187332a6cb0ccb65a59d9bc67c2ae650f4d3b4)暂为 `PENDING_CONTRACT_VERIFICATION`：本轮尚无足够可信的 expected universe 契约，不先建 coverage 计算并宣称全市场完整。日期连续、标的完整、缺口已记账必须分开；上游的待补账本不能自动满足 Vibe 事实完整性。不得为此引入第二套 Fact Lake / Data Health 或切换供应商。

## 全 A 快照可用性补充核查

主代理本轮通过隔离脚本取得的本机实测证据：两条东财 clist 首屏 HTTP 200、各 100 行、total=5920；按 1 秒加 jitter 串行执行完整分页，完成 25 页后整轮失败，完整分页失败记录仅为 `RuntimeError`，不能据此认定第 25 页明确发生连接失败。随后限定的第 24、25、26 页检查均为 `ConnectionError`，已停止追加联网探测。两阶段错误类型分别保留，不以后续检查替代整轮失败的错误证据。本调查仅引用主代理的实测结果，未独立请求行情接口、改变代理或复测。

- **原 Vibe：未发现本比较范围的新增提交明确修复全 A 长分页可用性。** 最近东财适配改动 [`34ed581`](https://github.com/simonlin1212/Vibe-Research/commit/34ed58155ca24c98f9009c2e83781f44ecc4a58f)是个股新闻 JSONP 的有界备用请求与引用，不是 clist。已读现有行情代码包含按首屏实际条数分页和同源主机回退，但不是此次新增长分页恢复证据。
- **vibe-astock：同样未发现明确的全 A 长分页修复。** [`266d901`](https://github.com/simonlin1212/vibe-astock/commit/266d90104c8f3e38b53c815b214c0115931396d9)是复盘取数边界与带日期解禁查询；已读 `vr/astock.py` 的成交额榜是 Top-N 请求，不能证明完整 5920 行快照可用。没有据此继续泛扩源码调查。
- **CNEquity 有同供应商参考路径，但核心并非新能力。** [v0.7.2 固定源码](https://github.com/rootSunc/CNEquity/blob/a18ee0484dfb0801650175471724def3228b8a17/src/cnequity/adapters/eastmoney/clist.py)已经具有 `fid=f12`、100 条分页、中途同页换主机、total 一致性 / 无推进 / 提前短页拒绝；此前 #202 只吸收 coverage 语义，没有吸收该客户端。[本次 HEAD 的主机表](https://github.com/rootSunc/CNEquity/blob/1650e384a3fd1f67a70144a489acc91432f1df27/src/cnequity/adapters/eastmoney/common.py)列出 push2、push2delay、40.push2；[后续提交](https://github.com/rootSunc/CNEquity/commit/a152a931c3b603f43ce97112972001f50bfbe239)给 clist 加入逐页原始响应与分页元数据归档。它们是代码参考，不是本机可用性证明。

同供应商备用主机仍可能共同失败；push2delay 涉及延迟语义，中途拼接不能仅凭数量满足就视为同一时点快照。上述路径保持 `REFERENCE_ONLY / LIVE_UNVERIFIED`，不得将已取 25 页发布为完整快照，也不因这些参考重启行情探测或更换代理。本调查没有找到已被证实能解决本机此次完整分页失败的上游修复。

## 验证范围

上游调查仅核对本地相关文档/代码/历史、公开 GitHub commits / compare / releases / 固定源码；未执行上游代码。适配实现的定向测试与隔离界面验收记录在对应 PR。真实全市场恢复仍未证实，未切换本机运行入口，也未启动正式 Product Reality 观察。

