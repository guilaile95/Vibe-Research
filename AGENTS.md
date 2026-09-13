# Agent Engineering Rules

本文件是 Vibe-Research 的项目代理规范唯一正文来源；其他文档只链接，不复制规则。
个人偏好遵循上层指令；本文件维护项目特有的授权、证据和数据边界。

## Recovery and source of truth

项目必须能脱离聊天历史恢复。接管项目、中断后恢复或 Stage / 授权 / 工程状态不确定时，执行一次恢复；同一任务连续工作只刷新影响决定的变化。
目标明确且不依赖项目状态的局部文档、提示词或错字调整，检查相关文件与本地 Git 即可；不因此自动扫描全部 Issue、PR 或 Notion。开始产品实现或处理发布、合并时仍须核对 live authority。

恢复入口为 `docs/CURRENT_STAGE.md`：它是坐标，不是 Engineering Truth 或第二个任务数据库。

恢复时读取 live stable 分支与 exact SHA、入口指向的授权 / 状态 authority 最新评论、Open Issues 和 Open / Draft PRs；再检查 active PR 的最新 review / comments、相关 CI 和 blocker 的代码与测试。只读当前任务需要的文档；需要长期产品 / 架构背景时读取入口点名的 Notion 页面，不全库扫描。不要求用户重述旧历史。

- **GitHub**：已提交实现、稳定分支、Issue / PR / review / CI、当前 freeze / override authority。仓库代码和 Git 状态优先于报告与旧文档。本地同时配置 origin 与 upstream 时，GitHub 命令明确指定目标仓库，不依赖 CLI 默认选择。
- **Local workspace**：未提交修改与 worktree 现场。先检查再修改，不能被远程状态覆盖。
- **Notion**：长期产品意图、架构约束和已验证经验；不替代 live 工程状态。
- 来源冲突写明 `SOURCE_CONFLICTS`；产品意图与实现冲突写明 `Intent vs Reality conflict`，不静默覆盖任何一侧。

恢复后输出一次以下字段。未读取或不可访问的事实标明限制，不猜测；没有本地访问能力时 `LOCAL_WORKSPACE = NOT_AVAILABLE_FROM_CURRENT_AGENT`。

```text
CURRENT ENGINEERING STATE

STABLE_BRANCH:
EXACT_STABLE_SHA:
AUTHORIZATION_STATE:
STATE_AUTHORITY:
CURRENT_STAGE:
ACTIVE_ISSUE:
ACTIVE_PR / HEAD:
LOCAL_WORKSPACE:
CI:
CURRENT_BLOCKER:
BLOCKING_DEFECTS:
PRODUCT_REALITY_BLOCKERS:
DEFERRED_SCOPE:
SOURCE_CONFLICTS:
NEXT_ACTION:
```

`BLOCKING_DEFECTS` 仅列阻塞当前工作的实际缺陷，不把产品优先级当成缺陷严重度。
`AUTHORIZATION_STATE` 从 live authority 解析；最新明确用户授权仅覆盖指定范围。
授权允许、下一步清晰且没有停止条件时，直接继续，不再等待一次确认。

## Authorization and delivery

- `FROZEN` 时不因候选池、清晰 Next Action 或历史 Draft 而自行开发。恢复不是重构授权；不自动复活旧 PR 或重开已冻结架构决定。
- 明确任务授权覆盖任务分支 / worktree、范围内代码与文档、相关测试、普通提交、推送任务分支、创建 / 更新 Draft PR，以及修复本轮发现的问题。
- 转 Ready、合并 PR、修改稳定分支、force push 和删除 worktree / 分支 / 备份等破坏性清理仍需单独明确授权；不可逆操作同时遵守用户确认口令要求。具体 Git 禁令见下文。
- 在当前会话内完成授权目标及验收。轻微歧义采用可回退假设继续；缺失信息影响目标、权限或不可逆结果时才停下澄清。遇到局部阻断先完成独立可做部分。
- 新实现前检查是否已有相关 active / open PR，避免重复路径。只审本轮 diff、关键调用链和受影响契约，不扩为全仓重设计。

## Evidence and verification

- Green CI、实现者自报或旧报告不是单独充分证据；结合实际 diff、关键 source-to-sink 与验收判断。配置存在或静态检查不等于运行时通过。
- 在所需验收已有充分证据时，Head 未变可复用审查与测试；Head 变化检查新增差异及影响；Base 变化检查冲突与相关回归。新会话本身不使证据失效。
- 测试服务于本次改动。复用相关现有检查，按受影响契约决定范围；纯文档改动无需默认跑后端、前端和 E2E 全套。新增测试遵守上层的最小覆盖约束。
- 本地验证使用隔离、可丢弃的 fixture / 数据目录；先确认所选命令不会写真实账户或持仓。范围内的此类验证与本次失败修复不需逐步确认。
- 产品真实使用证据与工程验证分开。CI、smoke、演示、合成数据不能证明 Product Reality，不能回填真实观察 Day 1。

## DRY

复用现有组件、Hook、测试与工具；当前业务逻辑的重复在能减少维护复杂度时收敛。不为假设中的复用创建通用框架、配置层或第二套实现。

状态只在其权威位置维护，其他文档链接引用；工作单只写目标、差异、验证和停止点。瞬时分支 / SHA / worktree 状态不写入长期产品文档。

删除、合并、迁移前的现场检查、关键契约的独立证据、fail-closed 条件和清晰接口边界不可因 DRY 而省略。

## Git

- 不使用 `git branch -D`、force push、`git clean`、`git reset`、`git restore`。
- 不对已推送提交执行 amend / rebase / squash；只创建普通新提交。
- 不修改稳定分支，不直接推送 main / 稳定分支。任何例外须有用户明确授权，不能从一般任务授权推断。
- 提交仅包含本次任务文件；保留用户未提交与已暂存的其他工作。

## Security boundaries

- 持仓、账户资金、模型 Key、复盘缓存留在用户目录 / localStorage / `VR_DATA_DIR`，不进 Git。
- 密钥、代理订阅和真实持仓不写入仓库或对话日志；疑似含密文件只记录路径与类型。
- 真实 `portfolio.json` / `account_profile.json` 不用于自动化测试写入，不向网络泄露账户资产。
- 不向客户端泄漏 ProxyError、完整 URL、traceback 或 SQL 语句。

## Reporting

一次交付结果、实际验证、偏差、剩余阻断与最终状态，不重复历史和未变化状态。
测试失败报告相关输出；跳过写明原因；未做运行时验证明确写“未完成运行时验收”。
不把待完成、未删除或静态检查描述为成功；不虚构评分、权重或产品效果。
