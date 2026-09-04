# Vibe-Research Reusable Conversation Handoff Protocol v1

> 状态：**PROJECT_HANDOFF_PROTOCOL_V1**
>
> 目的：让任何新的 ChatGPT / AI 会话在**不依赖旧聊天记忆**的情况下，基于 GitHub 当前 stable 状态恢复 Vibe-Research 的产品方向、授权任务、工程结构、在途 PR、Track Ownership、review blocker 与下一步动作。
>
> 本文件定义的是**恢复流程**，不是项目当前状态快照。短生命周期状态不得复制到这里长期维护。

---

## 1. 核心原则

```text
CHAT_MEMORY = HELPFUL_CONTEXT_ONLY

GITHUB_STABLE + GOVERNANCE_DOCS = PERSISTENT_PROJECT_MEMORY
```

新对话不得把旧聊天摘要、Agent 交付文本、README 或 CODE_WIKI 单独当作事实权威。

恢复项目时必须先解析 live repository，再继续开发或 review。

### 1.1 Live repo wins

如果以下信息发生冲突：

```text
旧聊天记忆
Agent handoff
旧 PR 报告
CODE_WIKI
PROJECT_STATE
exact-head source/tests
```

必须重新核验并按对应 authority 解释；不得为了保持旧聊天连续性而覆盖 live repo 事实。

### 1.2 Draft PR != stable capability

```text
Draft PR exists
!=
IMPLEMENTED_IN_STABLE
```

只有真正 merge 到 stable 后，该能力才可以被 PROJECT_STATE / CODE_WIKI 标记为 stable implemented。

### 1.3 CI PASS != independent review approval

```text
EXACT_HEAD_CI = PASS
!=
INDEPENDENT_REVIEW_APPROVED
```

CI 证明自动化合同通过，不替代 semantic / architecture review。

### 1.4 Track ownership > agent identity

项目按能力 Track 管理，不按“谁写过这个 PR”管理。

```text
Track
→ Capability
→ Active PR
→ Current owner
```

Agent 可以替换；Track semantic ownership 不应随 Agent 名字漂移。

---

## 2. 文档 Authority 与用途

新会话必须严格区分以下文档：

| 文档 | 回答的问题 | 不负责 |
|---|---|---|
| `docs/PRODUCT_NORTH_STAR_V01.md` | 产品长期应该是什么、语义/架构边界 | 当前实施授权 |
| `docs/NEXT_TASK.md` | 当前明确授权做什么、禁止做什么 | stable 已实现事实 |
| `docs/PROJECT_STATE.md` | stable 当前实际做到哪里 | 产品长期宪法 |
| `docs/CODE_WIKI.md` | 代码在哪里、现成能力、authority 导航、Anti-Rewheel | semantic truth / implementation authorization |
| `docs/ARCHITECTURE.md` | 相关模块怎么连接、调用链/数据流 | 当前任务授权 |
| `AGENTS.md` | 工程执行纪律 | 产品优先级 |
| `docs/CONVERSATION_HANDOFF.md` | 新会话如何恢复项目，以及项目级 Validation 执行协议 | 当前项目状态快照 |

### 2.1 解释优先级

产品/工程事实按以下原则解释：

```text
PRODUCT_NORTH_STAR
→ NEXT_TASK
→ exact-head source + tests
→ PROJECT_STATE
→ CODE_WIKI
→ README / historical research
```

`AGENTS.md` 是正交的工程纪律：适用时始终必须遵守。

---

## 3. 新对话 Bootstrap 固定流程

任何新会话准备继续 Vibe-Research 工作时，必须按顺序执行。

### STEP 1 — Resolve stable exact HEAD

先解析：

```text
repository = guilaile95/Vibe-Research
stable_branch = feature/research-system-v01
```

获得完整 40 位 SHA：

```text
CURRENT_STABLE_HEAD = <full sha>
```

**不得先假定旧聊天中的 stable SHA 仍然有效。**

### STEP 2 — Read Product North Star

读取：

```text
docs/PRODUCT_NORTH_STAR_V01.md
```

恢复：

- 产品身份
- Capital-First 优先级
- Decision Unit
- Thesis / Formal Decision / Risk / Evidence 语义
- P0/P1/P2/P3 路线
- Hard boundaries / non-goals

### STEP 3 — Read current authorization

读取：

```text
docs/NEXT_TASK.md
```

恢复：

- 当前明确授权工作
- 当前禁止项
- 哪些工作尚未授权

North Star 中存在某能力，不代表当前允许实现。

### STEP 4 — Read stable project state

读取：

```text
docs/PROJECT_STATE.md
```

恢复：

- stable 已经完成什么
- 当前阶段
- 已关闭 / 未关闭的能力
- consolidation 状态

### STEP 5 — Read CODE_WIKI

读取：

```text
docs/CODE_WIKI.md
```

用途仅限：

- subsystem 定位
- semantic authority 定位
- storage / API / dependency 导航
- Anti-Rewheel preflight

必须核对其中：

```text
Snapshot Branch
Snapshot Head
```

如果 CODE_WIKI snapshot 与当前 stable HEAD 不同：

```text
WIKI_STALE = POSSIBLE
```

只把 Wiki 当导航，关键 claim 回到 live source/tests 核验。

### STEP 6 — Read relevant architecture only

只有当前任务涉及对应 subsystem 时，再读取：

```text
docs/ARCHITECTURE.md
```

避免为了新会话恢复而无差别扫描全部代码。

### STEP 7 — Inspect active PRs

检查与当前 Track / NEXT_TASK 相关的 open PR，至少核验：

```text
PR number
base branch
base SHA
head branch
exact head SHA
Draft / Ready / merged
changed files
CI status
review status / blocker
```

Agent 交付文本只能作为待核验线索。

### STEP 8 — Verify high-value claims against exact-head source/tests

只验证当前工作真正需要的高价值事实，例如：

```text
semantic authority owner
public contract
store/read/write behavior
identity boundary
persistence model
time semantics
known blocker
```

不要求每次新会话扫描整个仓库。

### STEP 9 — Reconstruct Track Ownership

恢复格式必须以 Track 为中心：

```text
TRACK = <capability track>
OWNER = <current agent/person>
ACTIVE_PR = <number or NONE>
REVIEW_STATE = <state>
NEXT_ACTION = <immediate action>
```

### STEP 10 — Load execution policies

新会话继续任何 implementation / validation / review 工作前，必须确认：

```text
ANTI_REWHEEL_POLICY = LOADED
VALIDATION_POLICY = V2
FULL_SUITE_DEFAULT_BUDGET = 1
CI_IS_SEMANTIC_APPROVAL = NO
```

`VALIDATION_V2` 的唯一项目级协议见 §4.2。`CODE_WIKI.md` 只能引用，不维护竞争副本。

### STEP 11 — Produce Bootstrap Report before production work

恢复完成后先输出：

```text
NEW_CONVERSATION_BOOTSTRAP_REPORT
```

至少包含 §8 所定义的字段，然后才能继续下任务、改代码、review 或 merge。

---

## 4. Anti-Rewheel Preflight

每个新的 production slice 在实现前必须执行：

```text
ANTI-REWHEEL PREFLIGHT

1. Read relevant CODE_WIKI sections.
2. Resolve exact stable HEAD.
3. Verify Wiki claims against exact-head source/tests.
4. Search existing authority/service/store/tests.
5. Classify relevant capabilities:
   REUSE_AS_IS
   WRAP
   ADAPT
   REJECT_LEGACY
   NEW_REQUIRED
6. State what NEW decision information / assurance the new module adds.
7. Only then implement.
```

### 4.1 First-principles new-module test

任何新模块必须先回答：

> **它给系统增加了什么原来不知道的新决策信息、事实或 assurance？**

如果答案只是：

```text
重新命名已有状态
重新包装已有 authority
复制已有 store / projection
```

应优先拒绝或缩减，而不是新建 subsystem。

### 4.2 VALIDATION_V2 — Targeted-first execution contract

本节是 Vibe-Research 的项目级 Validation 执行协议。目标是提高**单位时间内的有效正确性证据**，而不是通过重复运行同一大测试集制造形式上的“更严谨”。

核心原则：

```text
CORRECTNESS
!=
MORE REPEATED FULL-SUITE RUNS

CORRECTNESS =
TARGETED TESTS
+ RELEVANT REGRESSION
+ ADVERSARIAL TESTS
+ EXACT-HEAD CI
+ INDEPENDENT SEMANTIC REVIEW
```

#### 4.2.1 Implementation loop — targeted first

开发迭代中默认只运行：

```text
changed capability targeted tests
+ directly affected regression tests
```

禁止默认模式：

```text
small change
→ full offline suite
→ another small change
→ full offline suite again
→ test-only change
→ full offline suite again
```

每次语义修改后应选择**能证明该修改正确性的最小高价值测试集合**。

#### 4.2.2 Final local validation

准备 commit / push 前，默认执行：

```text
TARGETED_FINAL
RELEVANT_REGRESSION
PY_COMPILE
GIT_DIFF_CHECK
```

适用时增加 domain-specific static/adversarial checks。

#### 4.2.3 Full-suite budget

默认：

```text
FULL_SUITE_DEFAULT_BUDGET = 1
```

含义：单个工作单最多进行 **一次有实质价值的最终本地 full-offline 尝试**，而不是每轮修改后重复跑。

第二次或更多 full-suite 只有在存在明确技术理由时才允许，例如：

```text
shared foundation changed
first full suite exposed cross-module regression
full-suite-only failure was fixed
validation environment materially changed
```

不得以以下理由重复运行：

```text
“为了更保险”
“刚又改了一点”
“习惯上再跑一次”
```

如果超出预算，最终报告必须填写：

```text
FULL_OFFLINE_RUN_COUNT = <N>
FULL_OFFLINE_RERUN_REASON = <specific reason>
```

#### 4.2.4 Local full offline is not automatically a hard gate

如果本地 full-offline 因会话、环境、资源限制而取消/未完成，但以下全部成立：

```text
TARGETED_TESTS = PASS
RELEVANT_REGRESSION = PASS / NOT_APPLICABLE
PY_COMPILE = PASS
DIFF_CHECK = PASS
EXACT_HEAD_CI = PASS
```

并且 exact-head CI 实际覆盖该工作单所需自动化合同，则：

```text
LOCAL_FULL_OFFLINE = NOT_COMPLETED
```

可以是 **NON_BLOCKING**。

反之：

```text
LOCAL_FULL_OFFLINE = PASS
EXACT_HEAD_CI = FAIL
```

绝不能通过自动化验证门禁。

#### 4.2.5 CI vs independent review

职责永久分离：

```text
EXACT_HEAD_CI
= AUTOMATED VALIDATION GATE

ChatGPT / project chief reviewer
= SEMANTIC / ARCHITECTURE / INTEGRATION GATE
```

因此：

```text
CI PASS
!= INDEPENDENT_REVIEW_APPROVED
```

CI 可以替代重复的本地 full-suite 执行，但不能替代 semantic / architecture review。

#### 4.2.6 Tool execution policy

同一阶段内相互独立的操作应在安全时并行：

```text
independent searches
independent reads
independent static checks
independent targeted test groups
```

有数据依赖、写冲突、同一路径更新或顺序语义的操作必须串行。

避免：

```text
read A → model → read B → model → grep C → model
```

如果三者互不依赖，应优先批量/并行获取后一次综合。

#### 4.2.7 Large-output policy

长测试日志、大型命令输出、重复 diagnostics 不应整段反复回灌模型上下文。

优先：

```text
persist/log full output when needed
→ inspect summary
→ inspect failed tests / relevant slices
```

模型上下文保留：

```text
PASS/FAIL
counts
failed test names
relevant traceback
high-value summary
```

而不是数千行已通过测试日志。

#### 4.2.8 Long-task phase discipline

复杂任务应按阶段组织：

```text
A. Anti-Rewheel / repo inspection
B. implementation
C. targeted validation / fixes
D. publish + exact-head CI verification
E. independent review
```

阶段边界是工作组织方式，不要求为每个阶段创建独立 PR 或无意义停顿。

如果出现大量重复 search/read、20+ 无必要串行工具循环、反复读取同一输出，应先压缩已有结论再继续。

#### 4.2.9 Required final-report fields

所有 G/T/Z production implementation / correction 工作单的最终报告至少包含：

```text
VALIDATION_POLICY = V2

TARGETED_TESTS =
PASS / FAIL

RELEVANT_REGRESSION =
PASS / FAIL / NOT_APPLICABLE

FULL_OFFLINE =
PASS / FAIL / NOT_COMPLETED / NOT_RUN

FULL_OFFLINE_RUN_COUNT =
0 / 1 / N

FULL_OFFLINE_RERUN_REASON =
NONE / <specific reason>

PY_COMPILE =
PASS / FAIL / NOT_APPLICABLE

DIFF_CHECK =
PASS / FAIL

EXACT_HEAD_CI =
PASS / FAIL / IN_PROGRESS / NOT_AVAILABLE

VALIDATION_DUPLICATION =
NO / <explanation>

PR_READY = NO
MERGE = NO
```

如果某项确实不适用，明确写 `NOT_APPLICABLE`，不得用另一个层级测试冒充。

#### 4.2.10 Review enforcement

主审在独立 review 时同时检查代码正确性与 Validation process 是否符合 V2。

无理由重复 full-suite：

```text
VALIDATION_PROCESS_V2 = NON_COMPLIANT
```

这不自动等于 production code 有 bug，但必须作为执行流程问题纠正。

反过来，如果：

```text
TARGETED = PASS
RELEVANT_REGRESSION = PASS
EXACT_HEAD_CI = PASS
LOCAL_FULL_OFFLINE = NOT_COMPLETED
```

主审不得仅为了形式完整要求重复运行数千测试；应根据 CI 覆盖和实际风险判断。

---

## 5. PR 生命周期

新会话恢复 PR 时统一使用以下状态语义：

```text
AUTHORIZED
↓
IN_IMPLEMENTATION
↓
READY_FOR_INDEPENDENT_REVIEW
↓
CHANGES_REQUIRED
↓
READY_FOR_INDEPENDENT_REVIEW
↓
INDEPENDENT_REVIEW_APPROVED
↓
READY
↓
MERGED
```

### 5.1 状态规则

```text
READY_FOR_INDEPENDENT_REVIEW
!= READY

CI PASS
!= INDEPENDENT_REVIEW_APPROVED

Draft
!= stable implemented

MERGED
= stable gains capability
```

除非用户明确授权，否则不得：

```text
auto Ready
auto Merge
direct push stable
force push
rebase/amend already-pushed reviewed history
```

---

## 6. Track / Agent 交接规则

### 6.1 Agent 替换

当用户将一个 Agent 的工作移交给另一个 Agent：

```text
OLD_AGENT exits scheduling
NEW_AGENT inherits Track context
```

但必须重新核验：

```text
active PR
exact head
review verdict
open blockers
```

不能仅根据旧 Agent 的描述继续。

### 6.2 Cross-track PR

如果某 Agent 临时实现了不属于其长期 Track 的 PR：

```text
PR author != long-term Track owner
```

后续治理按能力 Track 归属，不按作者永久归属。

### 6.3 Chief review

ChatGPT / project chief reviewer 负责：

- independent semantic review
- architecture conflict resolution
- authority boundary freeze
- integration order
- Ready / Merge gate
- post-merge documentation sync judgement
- Validation V2 process compliance review

Track Agent 不因为自己的测试全绿就自动获得 merge authority。

---

## 7. 旧对话 Closeout（可选）

只有当用户明确准备切换对话，或当前会话即将结束且有重要在途状态时，执行 Closeout。

### Closeout checklist

```text
1. Resolve latest stable exact HEAD.
2. List active Tracks.
3. List active PRs + exact heads.
4. Record independent review verdicts.
5. Record true blockers only.
6. Check NEXT_TASK / PROJECT_STATE sync need.
7. Check CODE_WIKI structural impact.
8. Check ARCHITECTURE structural impact.
9. Confirm VALIDATION_POLICY = V2 for future work.
10. Produce compact NEW_CONVERSATION_BOOTSTRAP block if useful.
```

### 不应进入长期文档的短生命周期状态

例如：

```text
CI 还剩 3 分钟
Agent 正在跑第 2 轮测试
本地 terminal 当前 PID
某个临时 worktree
```

除非它成为真正 blocker，否则不写入 Git 长期文档。

---

## 8. NEW_CONVERSATION_BOOTSTRAP_REPORT 标准输出

新对话在继续生产工作前至少给出：

```text
NEW_CONVERSATION_BOOTSTRAP_REPORT

REPOSITORY = guilaile95/Vibe-Research
STABLE_BRANCH = feature/research-system-v01
STABLE_HEAD = <full SHA>

PRODUCT_PRIORITY = <current priority>

ACTIVE_TRACKS =
- <track>
- ...

TRACK_OWNERS =
- <track> → <owner>
- ...

ACTIVE_PRS =
- #<n> <track> @ <head> / <Draft|Ready>
- ...

REVIEW_STATE =
- #<n> → <AUTHORIZED|IN_IMPLEMENTATION|READY_FOR_INDEPENDENT_REVIEW|CHANGES_REQUIRED|INDEPENDENT_REVIEW_APPROVED|READY|MERGED>

KNOWN_BLOCKERS =
- <only verified blockers>

MISSING_AUTHORITIES =
- <capability>

DO_NOT_TOUCH =
- <current protected items / constraints>

WIKI_SNAPSHOT_HEAD = <sha>
WIKI_MATCHES_STABLE = YES / NO

ANTI_REWHEEL_POLICY = LOADED
VALIDATION_POLICY = V2
FULL_SUITE_DEFAULT_BUDGET = 1
CI_IS_SEMANTIC_APPROVAL = NO

NEXT_ACTION =
<single immediate next action or active parallel actions>
```

如果某项无法从 live repo/docs 证明，必须写：

```text
UNKNOWN / NEEDS_VERIFICATION
```

不得凭旧记忆补齐。

---

## 9. 可重复使用的新对话启动词

用户可以在任何新对话中直接发送：

> 接管 Vibe-Research 项目。按仓库当前 stable 状态和 `docs/CONVERSATION_HANDOFF.md` 恢复上下文；不要把旧聊天记忆作为事实权威。先完成 Bootstrap Report，再继续当前项目工作。

如果需要更严格版本，可使用：

```text
接管 Vibe-Research 项目。

严格执行 `docs/CONVERSATION_HANDOFF.md`：

1. 先解析 `feature/research-system-v01` 当前 exact full HEAD。
2. 读取 PRODUCT_NORTH_STAR / NEXT_TASK / PROJECT_STATE / CODE_WIKI。
3. 当前任务需要时再读取 ARCHITECTURE，并始终遵守 AGENTS.md。
4. 检查相关 open Draft PR 的 base/head/changed files/CI/review state。
5. CODE_WIKI 只作导航；重要判断回到 exact-head source/tests。
6. Draft PR != stable implemented；CI PASS != independent review approved。
7. 恢复 Product Priority / Active Tracks / Track Owners / Active PRs / Blockers / Missing Authorities / Do-not-touch。
8. 开发前执行 Anti-Rewheel Preflight。
9. 加载 VALIDATION_V2：targeted-first、FULL_SUITE_DEFAULT_BUDGET=1、exact-head CI 是 automated gate 而非 semantic approval。
10. 不重复实现已有 Semantic Authority。
11. 不自行 Ready / Merge / direct push stable / force push。

先输出 `NEW_CONVERSATION_BOOTSTRAP_REPORT`，然后继续工作。
```

---

## 10. Emergency Handoff Fallback

如果新会话暂时无法访问 GitHub，只允许使用最小 fallback：

```text
REPOSITORY = guilaile95/Vibe-Research
STABLE_BRANCH = feature/research-system-v01

READ WHEN ACCESS RETURNS =
- docs/PRODUCT_NORTH_STAR_V01.md
- docs/NEXT_TASK.md
- docs/PROJECT_STATE.md
- docs/CODE_WIKI.md
- docs/CONVERSATION_HANDOFF.md

RULE =
Never trust this fallback over live repo state.
```

无法访问 live repo 时，不应执行需要 current-state 精确性的 Ready/Merge、migration、schema activation 或 authority replacement。

---

## 11. Post-Merge Documentation Sync

PR merge 后由主审判断文档影响。

### 高频更新

```text
PROJECT_STATE
NEXT_TASK
```

### 仅结构性变化更新

```text
CODE_WIKI
ARCHITECTURE
```

### 极低频更新

```text
PRODUCT_NORTH_STAR
AGENTS
CONVERSATION_HANDOFF
```

`CONVERSATION_HANDOFF.md` 只有在**项目恢复算法 / governance / validation protocol 本身改变**时更新；不要随着每个 PR 修改。

---

## 12. Machine-readable Bootstrap Contract

```yaml
protocol_version: conversation-handoff.v1

repository:
  name: guilaile95/Vibe-Research
  stable_branch: feature/research-system-v01

bootstrap:
  resolve_exact_head_first: true
  produce_bootstrap_report_before_work: true
  load_validation_policy: V2

documents:
  product: docs/PRODUCT_NORTH_STAR_V01.md
  authorization: docs/NEXT_TASK.md
  state: docs/PROJECT_STATE.md
  code_index: docs/CODE_WIKI.md
  architecture: docs/ARCHITECTURE.md
  engineering_rules: AGENTS.md
  handoff_protocol: docs/CONVERSATION_HANDOFF.md

governance:
  live_repo_wins: true
  chat_memory_is_authority: false
  handoff_text_is_authority: false
  wiki_is_semantic_authority: false
  draft_pr_is_stable: false
  ci_pass_equals_review_approval: false
  track_ownership_over_agent_identity: true
  independent_review_required: true
  direct_push_stable_allowed: false
  force_push_allowed: false

anti_rewheel:
  required_before_new_production_slice: true
  require_exact_head_verification: true
  require_new_information_test: true

validation_v2:
  targeted_first: true
  relevant_regression_required: true
  full_suite_default_budget: 1
  repeated_full_suite_requires_reason: true
  local_full_not_completed_is_automatically_blocking: false
  exact_head_ci_required_for_final_automated_gate: true
  exact_head_ci_equals_semantic_approval: false
  independent_review_required: true
  parallelize_independent_tools_when_safe: true
  summarize_large_outputs: true
  require_final_report_fields: true

post_merge_docs:
  project_state: evaluate_every_merge_wave
  next_task: evaluate_every_merge_wave
  code_wiki: structural_changes_only
  architecture: structural_changes_only
  handoff_protocol: protocol_changes_only
```

---

## 13. Protocol invariants

以下原则永久适用于本协议，除非用户明确修改项目治理：

```text
Live repo > stale conversation context
Exact-head evidence > handoff prose
Track ownership > agent identity
Draft != stable
CI PASS != semantic approval
Wiki locate != verify
Unknown != healthy
Anti-rewheel before implementation
Targeted-first validation
Full-suite default budget = 1
Repeated full-suite requires explicit reason
Exact-head CI = automated validation gate
Independent review = semantic / architecture / integration gate
Merge before stable documentation promotion
```
