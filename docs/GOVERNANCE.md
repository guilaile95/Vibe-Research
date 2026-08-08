# 项目治理契约（Project Governance v0.1）

> 本文件是 Git/GitHub 治理、文档权威链、CI 门禁与 PR 恢复方案的唯一正文。
> 项目总体状态见 [`docs/PROJECT_STATE.md`](PROJECT_STATE.md)（唯一状态权威）；
> 当前授权任务见 [`docs/NEXT_TASK.md`](NEXT_TASK.md)。

## 1. 文档权威链（GOV-01 结论）

| 文档 | 职责 | 更新时机 | 是否状态权威 |
|---|---|---|---|
| `docs/PROJECT_STATE.md` | 稳定分支事实 + 项目总体状态 | 功能合并至稳定分支、授权变化时 | **是（唯一）** |
| `docs/NEXT_TASK.md` | 唯一当前授权任务 | 授权变更时 | 是（任务） |
| `docs/GOVERNANCE.md` | 治理契约（本文件） | 治理变更时 | 是（治理） |
| `docs/PRODUCT_BACKLOG.md` | 候选池边界、实现状态、授权状态 | 候选授权/完成/新增时 | 候选 |
| `docs/ARCHITECTURE.md` | 已实现架构 + 明确标注未实现部分 | 架构变更时 | 实现事实 |
| `docs/KNOWN_ISSUES.md` | 已知限制与测试例外 | 发现/修复限制时 | 限制 |
| `docs/DECISIONS.md` | 设计决定（历史记录） | 新决定时（追加，不改写） | 历史 |
| `docs/CHAT_HANDOFF.md` | 交接摘要 + 安全边界 | 大变更时 | 否（执行记录） |
| `docs/research/EXECUTION_STATE.md` | BK-11 执行历史 | 仅追加已验证研究事实 | 否（历史） |
| `docs/research/*` | 研究/设计稿 | 各自标注状态 | 视标注 |
| Issue / PR | 对应专项局部状态 | 专项变更时 | 局部 |

规则：

- 状态只在**一个权威位置**维护；其他文档链接引用，不复制完整状态（DRY）。
- 瞬时状态（Draft、worktree 存在性、锁定情况）不写入长期文档，以
  `git worktree list` / GitHub 现场为准（AGENTS.md）。
- 历史文档不得继续冒充"当前状态"：2026-08-07 已批量修正基线 SHA、
  授权声明、测试数量、"未实现"声明、账户资金状态等 15 处冲突。
- 具体测试数量不在文档维护（以 CI 与本地实测为准），避免过期快照。

## 2. GOV-00 历史核验快照（2026-08-07）

下表保留 GOV-00 执行当日的审计事实，不是当前项目状态权威；PR、分支与模板的
当前状态以 GitHub 现场和 `docs/PROJECT_STATE.md` 为准。

| 项 | 实际状态 | 与交接偏差 |
|---|---|---|
| 稳定分支 | `feature/research-system-v01` @ `cd17fec2`（protected=false） | 无 |
| 仓库 | private、default_branch=stable、当前账号 admin、未归档 | 无 |
| 分支保护 API | **403：Upgrade to GitHub Pro or make this repository public** | 交接仅说"off"；实际连开启选项都没有 |
| Rulesets API | 403（同因） | 同上 |
| PR #47 | OPEN / Draft / MERGEABLE / CLEAN；head `4e479205`、base `cd17fec2`；CI success | 无 |
| PR #43 | OPEN / Draft / **CONFLICTING / DIRTY**；head `0730f4bc`、base `ad844742`（非当前 stable） | 无 |
| Issue #48 | OPEN，正文 PAUSED / ARCHIVED（2026-08-06 20:12 +08:00） | 无 |
| CI | 历史快照当时为 1 个 workflow、6 jobs；当前 job 清单以 §3 为准 | 当前已增至 8 jobs |
| 合并设置 | merge/squash/rebase 全开；auto-merge off；delete-branch-on-merge off | 无 |
| CODEOWNERS / PR template / issue template / SECURITY / CONTRIBUTING | 均不存在 | 无 |

## 3. CI 门禁分级

稳定分支 `ci.yml` 现有 8 个 job；PR #53 合并后使用
`actions/checkout@v7`、`actions/setup-python@v6`、`actions/setup-node@v6`：

| Job | 内容 | 分级 | 理由 |
|---|---|---|---|
| `backend` | `pytest -m "not live"`（离线单测） | **REQUIRED** | 离线、确定性、可重复、不写生产 |
| `frontend` | `npm run build` + `npm test` | **REQUIRED** | 同上 |
| `windows-lock-check` | Windows authority lock 再生成 + exact lock 安装 + 离线单测 | **REQUIRED** | 双平台依赖可复现门禁；离线、确定性 |
| `whitespace` | `git diff --check` | **REQUIRED** | 确定性、零依赖 |
| `e2e-smoke` | Playwright smoke + top-risk（起本地服务、访问实时数据源） | OPTIONAL | 稳定但依赖运行时/实时数据 |
| `e2e-thesis-smoke` | evidence-thesis real E2E | OPTIONAL | 同上 |
| `e2e-data-health-smoke` | data-health E2E | OPTIONAL | 同上 |
| `e2e-intel-digest-smoke` | Intel digest E2E（PR #50 新增） | OPTIONAL | 同上 |

REQUIRED 标准：离线、deterministic、可重复、不写生产数据、不依赖第三方实时服务。

禁止设为 required 的类别：live 网络探测、第三方行情接口、需要 Token 的测试、
BK-11 shadow、真实盘中测试。

FUTURE（BK-10 候选，未授权）：lint/format（ruff/eslint）、类型检查
（mypy/pyright）、覆盖率门控、pre-commit hooks、依赖更新 bot。

GitHub Branch Protection 使用的真实 check contexts 为：`Backend tests`、
`Frontend build & test`、`Python Windows lock check`、`Whitespace check`。
四个 Playwright E2E job 继续保持 OPTIONAL，不进入 required checks。

## 4. GitHub 稳定分支保护（GOV-02）

### 当前配置（2026-08-08）

- 仓库已由 Private 转为 Public；历史 Private + Free 的 API 403 见 §2，不改写历史；
- 保护机制：**legacy Branch Protection**；Repository Rulesets 保持 0，避免重复控制；
- 目标分支：`feature/research-system-v01`；
- Required checks：`Backend tests`、`Frontend build & test`、
  `Python Windows lock check`、`Whitespace check`；
- `strict: false`：checks 必须成功，但不强制 base 每次移动后重新运行整套 CI；
- `allow_force_pushes: false`、`allow_deletions: false`；
- Required approvals：0；CODEOWNERS approval：关闭；conversation resolution：关闭；
- `enforce_admins: false`：仓库管理员保留 emergency bypass，避免单人项目锁死；
- linear history、signed commits、push restrictions、branch lock、deployments 均不强制。

### 机制选择

只保护一个稳定分支时，legacy protection 能直接表达 required checks、force/delete
限制与管理员 bypass，维护成本低于 ruleset 的 actor/bypass 配置，也与现有治理契约一致。
因此不同时创建 ruleset。

### 仓库内纪律

1. AGENTS.md 规则正文：禁 force push、`git branch -D`、`git clean`、
   `git reset`、`git restore`、对已推送提交 amend/rebase/squash；
2. 所有功能走独立分支 + Draft PR（Draft 原生不可合并）；
3. 稳定分支只通过"Merge PR"进入（历史全部为 merge commit，可回看）；
4. Branch Protection 是远端硬门禁，仓库内规则继续约束本地操作与代理行为。

不做的事：企业级规则（多人 review、CODEOWNERS 全员、线性历史强制、锁定文件）。

## 5. 协作基础决策（GOV-03）

| 项 | 决策 | ROI 判定 |
|---|---|---|
| `.github/CODEOWNERS` | 不添加 | **LOW ROI**（无 teams/多所有者，单人项目无意义） |
| `.github/PULL_REQUEST_TEMPLATE.md` | **已添加**（最小验证清单，与现有 PR 报告习惯一致） | MEDIUM（低成本防遗漏） |
| issue template | 不添加 | **LOW ROI** |
| `SECURITY.md` | 不添加 | **LOW ROI**（个人研究仓库，无独立安全响应流程或线上服务） |
| `CONTRIBUTING.md` | 不添加 | **LOW ROI**（单人项目） |

## 6. PR #43 Recovery 评估（2026-08-07，只读评估，未执行）

> **状态：COMPLETED / superseded by PR #50**（2026-08-07 合并）。
> 本节为历史评估记录；实际执行已完成（recovery 分支合并、旧 PR #43 关闭），
> 下文"执行路径"不再作为待执行任务。

### 根因

- `mergeable=false` = 真实内容冲突 2 处：`backend/app.py`、
  `frontend/package.json`。均为同位置各加一行、语义相加即解
  （stable 加 `bk11_history_router` / `test:e2e:bk11-history`，PR 加
  `intel_digest_router` / `test:e2e:intel-digest`）；`api.ts`/`types.ts`
  自动合并干净。
- PR base = `ad844742`（PR #41 合并点），落后 stable 3 个合并
  （#44/#45/#46）+ 104 个提交（BK-11 阶段，merge-base 实测）。

### 16 文件评估

16/16 值得保留：8 个为 PR 新增（stable 无对应），8 个为修改
（仅上述 2 处位置冲突；`newsradar.py` 是兼容增强，其余零冲突）。
stable 无 Intel Daily Digest 同类实现；schema 零冲突（独立 SQLite）；
API 前缀 `/intel-digests*` 无碰撞。

### 推荐：C（从稳定 Head 建 recovery 分支迁移有效改动）

- A（rebase 原 PR）：否决——需 force-push，违反 AGENTS.md；
- B（merge stable into 原 PR）：可行但 diff 将膨胀到约 87 文件
  （base 缺整个 BK-11 阶段），review 噪音大；
- D（放弃）：否决——2857 行完整功能，阻断为外部因素（GitHub billing）。

### 执行路径（下一阶段 "PR43 Recovery v0.1"，本阶段不执行）

1. 从 `cd17fec2` 切 `feat/intel-daily-digest-v0.1-recovery`；
2. 按序 cherry-pick `64c5b59` → `4c8f97e` → `c2f7af4` → `0730f4b`；
3. 解 2 处冲突（app.py 两个 router 并存；package.json 两个 e2e script 并存）；
4. 本地验证：`pytest backend/tests/test_intel_digest_api.py`、
   `pytest backend -m "not live"`、`npm test`、`npm run build`、
   `npm run test:e2e:intel-digest`；
5. push 新分支 → 新 PR（base `feature/research-system-v01`）→ 关闭 PR #43
   （均需授权）；
6. 外部阻断：CI 全绿需 Owner 恢复 GitHub billing（所有路径共通）。

## 7. 决策记录（2026-08-07）

| 决策 | 理由 |
|---|---|
| 建立唯一状态权威链（PROJECT_STATE 唯一） | 消除多文档互斥；DRY |
| 修正 15 处文档冲突 | 基线 SHA、授权、测试数、账户资金、未实现声明等 |
| 分支保护在免费私有仓库不可用 → 纪律替代 + 模板 | 403 实测；不锁死 |
| 采纳 PR template；其余协作文件 LOW ROI | 单人项目最小必要 |
| PR #43 推荐 recovery 分支方案（C） | 独立代码评估，非照抄交接偏好 |

## 8. 当前治理边界

- 仓库当前为 Public，License 为 MIT；GitHub 元数据 `fork=false` 不改变上游代码来源；
- `PLATFORM_BRANCH_PROTECTION_UNAVAILABLE` 已于 2026-08-08 **RESOLVED / CLOSED**；
- 稳定分支使用 §4 的单一 legacy Branch Protection，不创建重复 ruleset；
- PR template、Draft PR、完整 CI 与人工 merge discipline 继续作为配套控制；
- 当前授权只以 `docs/NEXT_TASK.md` 为准，历史 recovery 评估不构成新任务授权。
