# Agent Engineering Rules

本文件是 Vibe-Research 中 AI 与工程代理工作规范的**唯一正文来源**。
其他文档（`docs/DECISIONS.md`、`docs/CHAT_HANDOFF.md` 等）只引用本文件，不复制规则正文。

## Agent Recovery Entry

本项目必须能够在**没有历史聊天记录**的情况下恢复。

### 什么时候执行恢复流程

仅在以下情况执行一次完整恢复：

- 新对话 / 新模型接管；
- 中断任务恢复；
- 当前 Stage、授权状态或 live engineering state 不确定；
- 用户明确要求重新接管项目。

普通同一任务的连续开发不要反复执行全量恢复。

### Fast Recovery

开始显著工作前：

1. 读取 `docs/CURRENT_STAGE.md`。
2. 检查 live GitHub：
   - 当前稳定分支与 exact stable SHA；
   - `docs/CURRENT_STAGE.md` 指向的状态 / 授权 authority 最新评论；
   - 当前 Open Issues；
   - 当前 Open / Draft PRs；
   - active PR 最新 review / comments；
   - relevant CI；
   - 当前 blocker 对应的代码和测试。
3. 读取 `docs/CURRENT_STAGE.md` 中列出的 GitHub / repo 文档；只读当前 Stage 真正需要的内容。
4. 需要长期产品 / 架构背景时，通过已连接的 Notion 读取 `docs/CURRENT_STAGE.md` 点名的页面；不要全库扫描。
5. 不要求用户重新拼接或复述旧聊天历史。

`docs/CURRENT_STAGE.md` 是**恢复坐标，不是 Engineering Truth，也不是第二个任务数据库**。

如果它与 live GitHub 冲突：

- 明确报告 `SOURCE_CONFLICTS`；
- 当前实现、PR、CI、Issue 状态以 live GitHub 为准；
- 产品长期意图与实现冲突时报告 `Intent vs Reality conflict`，不要静默覆盖任一侧。

### Required First Output

恢复完成后先输出一次：

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

其中：

- `LOCAL_WORKSPACE`：能访问本地仓库时必须先检查未提交修改 / worktree；不能访问时写 `NOT_AVAILABLE_FROM_CURRENT_AGENT`，不得猜测。
- `BLOCKING_DEFECTS`：只列真实会阻塞当前工作的缺陷，不把产品优先级 P0/P1 标签混进缺陷等级。
- `AUTHORIZATION_STATE` 必须从 live authority 解析。若为 `FROZEN`，不得仅因为 Next Action 清晰就自行开发；若当前用户指令已明确解冻 / 授权，则按最新用户指令和 live GitHub 记录继续。

若 `NEXT_ACTION` 清晰、授权允许、且没有 Stop / Escalation 条件，恢复报告后直接继续，不等待用户再次确认。

### Recovery Discipline

- 开始新实现前先检查 active / open PR，已有实现则继续或审查，不创建重复路径。
- Green CI、实现者自报、旧 Agent 完成报告都不是单独充分证据；对当前任务检查实际 diff、关键 source-to-sink 和 acceptance。
- 不因新会话自动重开已经冻结的架构决定；只有代码、测试、真实使用或明确新产品方向提供反证时才重开。
- 先读当前 Stage 相关代码，不做 repository-wide redesign / audit。
- Recovery 不是重构授权。
- 新增基础设施前先复用现有 capability。
- 历史 Draft PR 默认是历史上下文，不自动复活。

### Source Roles

**GitHub = current Engineering Reality**：代码、稳定分支、Issues、PRs、reviews、tests、CI、当前授权 / freeze authority。

**Notion = durable Product / Architecture Context**：Product North Star、长期 invariant、Architecture Direction、已验证 lessons、research conclusions、stage-transition reasoning。

**Local workspace = uncommitted execution reality**：用户未提交修改、worktree、临时验证现场。不得被远程状态静默覆盖。

### Recovery Handover

正常跨模型 / 新对话交接只需要给出：

```text
接管项目

先读 AGENTS.md，
通过已连接的 GitHub + Notion 自主恢复项目。

不要依赖聊天历史。

恢复后输出 CURRENT ENGINEERING STATE，
然后继续当前最高优先级且未阻塞的工作。
```

交接传递恢复坐标，不重新编写项目历史。

## Source of truth

- 仓库代码和 Git 状态优先于完成报告与旧文档。旧文档与 AI 报告不能覆盖实际代码与 Git 状态。
- 当前明确授权优先于候选池。候选池中的条目不构成开发授权。
- 状态只在一个权威位置维护，其他文档使用链接指向该位置。
- 事实来源优先级：稳定分支代码与 Git 状态 > GitHub PR 状态 > 本地目录现场 > 已验证的测试报告 > 旧文档与完成报告。

## Delivery and execution

- 默认在当前会话内端到端完成用户提出的问题，不把可一次闭环的任务拆成“计划、核验、工作单、执行、再核验、再报告”多轮对话。
- 用户明确授权一项任务后，该授权默认覆盖：使用任务分支或 worktree、修改任务范围内代码与文档、运行测试、创建普通提交、推送任务分支、创建或更新 Draft PR，以及修复本轮审查发现的问题。
- 仍需单独明确授权的只有：修改或直接推送稳定分支、转 Ready 或合并 PR、force push，以及删除 worktree、分支、备份或其他破坏性清理。
- 轻微歧义由执行者采用最合理且可回退的假设继续完成，并在最终报告中说明；只有缺失信息会导致安全风险、不可逆结果或无法确定目标时才中断询问。
- 只核验会影响本轮决策的事实。新会话不会自动使已有证据失效：Head 未变化则复用已有审查与测试证据；Head 变化只审新增差异及受影响范围；Base 变化才检查冲突和相关回归。
- 默认审查当前 Diff、相关契约和阻断风险，不重新审计与本轮无关的整个仓库、全部历史 worktree 或所有长期文档。
- 能继续的工作必须先完成。遇到单一阻断时，完成全部非阻断部分，并一次性报告阻断原因、影响和唯一需要用户决定的事项。

## DRY

所有代码、测试、文档、工作单和完成报告默认遵循 DRY。

- 路径、分支、SHA、命令和停止条件集中定义后复用，不在多处硬编码。
- 重复业务逻辑提取为共享函数、模块、组件或配置。
- 多份文档不得分别维护同一状态。瞬时执行状态（Draft、worktree 存在性、锁定情况）不写入长期文档。
- 工作单只描述目标、差异、验证和停止点，不重复历史背景。
- 完成报告只报告结果、偏差和最终状态。
- 优先扩展现有测试、组件、Hook 和工具，不创建功能重叠的实现。落地新能力前先检索仓库内是否已有可复用实现。
- 不为尚未出现的复用需求进行投机式抽象。单一调用点不需要通用框架。

## Exceptions

以下重复是有意且允许的，不得以 DRY 为由删减：

- 删除、合并、迁移前的现场安全检查。
- 关键契约的独立测试证据。
- 失败关闭（fail-closed）条件。
- 为避免隐式耦合而保留的清晰接口边界。

DRY 不得用于减少必要验证或隐藏关键安全条件。

## Reporting

- 最终报告应一次性给出结果、实际验证、偏差、剩余阻断和最终状态；不重复完整历史、交接正文或未变化状态。
- 报告结果必须忠实：测试失败就贴输出；步骤跳过就说明跳过；未做运行时验证就写“未完成运行时验收”，不得把静态检查写成运行时通过。
- 实际删除失败时不得写“已删除”。
- 不虚构无来源的评分或权重。

## Git

- 不使用 `git branch -D`、force push、`git clean`、`git reset`、`git restore`。
- 不对已推送提交执行 amend / rebase / squash。
- 只创建普通新提交。
- 不修改稳定分支；不直接推送 main / 稳定分支。

## Security boundaries

- 持仓、账户资金、模型 Key、复盘缓存留在用户目录 / localStorage / `VR_DATA_DIR`，不进 Git。
- 不把密钥、代理订阅、真实持仓写入仓库或对话日志。
- 真实 `portfolio.json` / `account_profile.json` 不用于自动化测试写入。
- 不向客户端泄漏 ProxyError、完整 URL、traceback 或 SQL 语句；不向网络泄露账户资产。
- 对疑似含密文件只记录路径与类型，不输出内容。
