# Frontend Workspace P2 独立审查报告

日期：2026-08-09  
审查对象：`agent/frontend-workspace-p2`  
实现提交：`9065439b518fbe669610575c426805b346525d8b`  
稳定基线：`d06eabac093e0bc0acace4abe1e446b3655629f5`

## 结论

当前变更适合继续保留在 Draft PR 中接受 GitHub CI 验证；不应仅凭本报告直接转 Ready 或合并。

- P0：0
- P1：0
- P2：0（独立审查发现的受限 `localStorage` 问题已在发布前闭合）
- P3：3 项非阻断观察

## 审查范围

- Daily Review 页面结构、AI 面板隔离和 Markdown 延迟加载。
- Stock Data 次要数据按可见区域延迟请求。
- 交易、持仓、决策反馈和决策证据弹窗的键盘与焦点契约。
- Settings、Data Health、GlassCard 和搜索输入的可访问性。
- Daily Review 全球指数真实分时走势，包括美股、港股、日经 225、韩国 KOSPI 和上证指数。
- API 与 Daily Review 类型拆分后的兼容 facade。
- 相关前端契约测试和后端全球指数测试。

## 主要问题与处理结果

| 领域 | 原问题 | 当前结果 |
| --- | --- | --- |
| 组件与性能 | Daily Review 秒级 AI 计时导致大页面重渲染；Markdown 进入页面即加载 | AI 卡片和时钟隔离；Markdown 按内容延迟加载 |
| 请求性能 | Stock Data 首屏同时触发多路次要请求 | 次要区块接近视口时再请求，并防止跨股票旧响应覆盖 |
| 弹窗 a11y | 缺少统一 dialog、Esc、Tab 焦点陷阱、焦点恢复和可靠标题关联 | 统一为 `AccessibleDialog`；保留各页面原有遮罩关闭语义 |
| 控件 a11y | 卡片、radio、详情入口和搜索框存在键盘或标签缺口 | 已改为原生语义或补齐键盘、label 契约 |
| 响应式 | 全球市场表格在窄屏依赖横向滚动 | 移动端采用纵向摘要，桌面保留表格 |
| 全球走势 | 缺少真实分时对比以及日本、韩国、上证 | 8 个指数真实曲线、交易日期、来源、时区和更新时间均显式展示 |
| 数据可靠性 | 外部源可能超时、部分缺失、重复冷请求或泄漏错误详情 | 总预算、单源超时、single-flight、partial 短缓存、失败隔离和错误脱敏已实现 |
| 本地偏好 | 受限存储环境抛出 `SecurityError` 可能阻断隐私模式或 AI 面板 | 读取和写入均失败开放；仅丢失持久化，不阻断页面 |

全球走势不构造随机或模拟数据。腾讯负责恒生指数、恒生科技和上证指数；Yahoo 负责美股、日经 225 和韩国 KOSPI。单源失败会进入缺失列表，不跨源拼接。

## 验证证据

- `git diff --check`：PASS。
- 前端单元/契约测试：366 passed，0 failed。
- 前端生产构建：PASS，Vite 转换 2109 modules。
- 全球指数后端专项：6 passed。
- Daily Review 与市场受影响范围回归：67 passed。
- 真实本地 API 探测：8/8 指数返回，`missing_keys=[]`；页面桌面/移动端均渲染 8 条曲线且无文档级横向溢出。
- `test:e2e:workspace-p2`：120 秒内无输出并超时，未取得 PASS 证据，也未观察到失败断言。该项必须如实视为未完成。
- 本地后端全量测试：超过 180 秒工具上限，未取得完整结论；不能记为 PASS。

发布前远端旧 Head 的 CI 后端失败来自既有 `test_concurrent_create_different_rule_ids` 并发竞态（4079 passed、1 failed），不在本次改动路径中。新 Head 的 CI 结果以 Draft PR checks 为准。

## 非阻断观察

1. 一部分新增测试属于源码契约测试，适合防结构回退，但不能替代浏览器行为测试。
2. 全球走势 flight/cache 为进程内控制；多 worker 部署时每个 worker 独立。当前个人本地单进程边界可接受。
3. Daily Review 类型拆分仍有 type-only 循环，当前构建通过，可在后续模块化工作中清理。

## 发布门禁

`SUITABLE_FOR_DRAFT_PR = YES`

`READY_FOR_MERGE_REVIEW = PENDING_GITHUB_CI_AND_E2E_EVIDENCE`

本报告不授权 Ready、merge 或修改稳定分支。
