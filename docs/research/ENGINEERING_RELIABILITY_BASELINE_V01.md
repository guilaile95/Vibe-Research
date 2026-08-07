# 工程可靠性基线（Engineering Reliability Baseline v0.1 — Phase A Qualification）

> 阶段：测量审计（Phase A），**未实施任何改造**。基线：stable
> `feature/research-system-v01` @ `060b5d0eb03c950390d0dcb2524eab0c19be021d`
> （2026-08-08 实测）。原则：先测量，后改造；本阶段零代码修改。

## 1. 结论摘要

- 无 P0；无 P1（无真实密钥泄漏、无生产可利用漏洞）。
- Python 依赖**不可复现**（无任何 lock/constraints，60 包图每次安装现场解析）——
  最高优先级工程债。
- npm audit 3 个 high 均属**构建链/传递依赖**，Vite SPA 无 Node 生产运行时，
  `EXPLOITABLE_IN_THIS_APPLICATION = false`，维持 VULNERABILITY_EXISTS 记录。
- GitHub Actions 供应链干净（permissions 最小、零 secrets、无 untrusted input）；
  唯一 RISK：checkout@v4/setup-node@v4 的 Node 20 弃用警告。
- CI 最近 30 run：2 次 flake（thesis E2E 1/30 ≈ 3.3%；backend 测试竞态 1 次），
  thesis E2E 维持 **P2 reliability debt**。
- Python 静态基线：ruff 1191 项（62.5% 可自动修）、mypy 212 错误/56 文件，
  无第三方噪音；TypeScript：strict 全绿（tsc 0 错误），无 ESLint。
- 密钥扫描：无真实 secret；1 项 P3 注意（gstock.py 公开端点常量）。

## 2. REL-01 Python 依赖可复现性

- `backend/requirements.txt`（6 个 `>=`：fastapi/uvicorn[standard]/akshare/mootdx/
  pytest/httpx；2 个裸包名：requests、pandas）+ `requirements-dev.txt`。
- 全树无 pyproject.toml / setup.cfg / Pipfile / poetry.lock / uv.lock /
  constraints*.txt → **不存在真正的 lock/constraints**。
- transitive 全部由 pip 现场解析；CI（Python 3.11）与本地（3.12.10）存在
  解释器漂移 + 时间漂移（今日实测解析到 pandas 3.0.5、pytest 9.1.1、
  fastapi 0.141.1，均为最新 major）。
- 新环境**无法**重建与当前 stable 相同的 dependency graph；resolver drift 风险
  高（`cache: pip` 只缓存下载不固化解析）。
- **推荐：C（pip-tools）**——8 个 direct deps 小图，`pip-compile` 生成
  `requirements.lock` 锁 60 包全图，保留手写 requirements.txt 作人类声明；
  与前端 package-lock 模式对齐；不引入 uv 整套新工具链（LOW ROI）。

## 3. REL-02 前端依赖审计

- `package-lock.json`（lockfileVersion 3，300 条记录）与 package.json 一致；
  `npm ci` 完全由 lockfile 确定版本（干净复现 249 包、~20s、无 integrity 错误）。
- `npm audit`：**3 high / 0 critical**，来自 2 个 advisory、命中 3 个包节点：

| 包 | 版本 | direct/transitive | dev/runtime | 判定 |
|---|---|---|---|---|
| postcss | 8.5.16 | transitive（构建链） | dev | VULNERABILITY_EXISTS；生产不可达 |
| react-router | 7.18.1 | direct | runtime（浏览器） | 同上（advisory 场景不适用当前用法） |
| react-router-dom | 7.18.1 | direct | runtime（浏览器） | 同上 |

- `EXPLOITABLE_IN_THIS_APPLICATION = false`：本项目为 Vite 静态 SPA，无
  SSR/RSC/Node 生产运行时；postcss 仅构建期执行。**不升级为 P1**；升级
  依赖留待实现阶段（本轮禁止）。
- 环境差异：本机 Node 26.4 / npm 11.17 vs CI Node 22。

## 4. REL-03 GitHub Actions 供应链

| 项 | 结果 | 分类 |
|---|---|---|
| Actions | 仅官方 `actions/*`（checkout@v4 ×7、setup-python@v5 ×4、setup-node@v4 ×5）；playwright 为 lockfile 内 devDependency | CONFIRMED |
| SHA pin | 全部 major tag；单人私有仓库、无第三方 action → 收益低 | LOW_ROI_HARDENING |
| permissions | `contents: read`（最小） | CONFIRMED 合规 |
| secrets | 零引用 | CONFIRMED |
| cache | setup-python/setup-node 按依赖文件哈希缓存；私有仓库无 fork 投毒面 | LOW_ROI_HARDENING |
| untrusted input | whitespace job 仅插 SHA 类值；无 PR title/issue 正文进入 shell | CONFIRMED 安全 |
| fork/PR 风险 | 私有仓库；无 pull_request_target、无 secrets | 无场景 |
| Node 弃用 | run 日志：`Node.js 20 is deprecated...forced to run on Node.js 24`（checkout@v4、setup-node@v4） | **RISK** |

建议（实现阶段）：升级 checkout/setup-node 至支持 Node 24 的新 major
（如 @v5，升级前验证存在性）；其余为 LOW_ROI 不实施。

## 5. REL-04 CI 可靠性统计

窗口：最近 30 条 run（`gh run list --limit 30`）：

| 指标 | 值 |
|---|---|
| runs_examined | 30 |
| 当前结论 success / failure | 30 / 0 |
| rerun_count（attempt>1） | 2 |
| flake_count（首 attempt 失败→同 head 复跑成功） | 2 |
| failure_by_job | thesis E2E ×1；Backend tests ×1 |

- thesis flake：run `31200057732`（head 1339f7a）attempt 1 失败于
  "Updated evidence text not visible"（UI 可见性时序断言），attempt 2 成功。
  **频率 1/30 ≈ 3.3%**，维持 **P2 reliability debt**（rerun PASS 不删除记录，
  根因未修）。
- 新发现：Backend tests 亦出现 1 次间歇失败（run `31071803129`，
  `test_analyze_disconnect_during_save_cancels_transaction` threading.Event
  竞态，attempt 2 成功）→ 登记 P2（测试时序竞态）。

## 6. REL-05 静态质量基线

### Python（ruff 0.16.2 / mypy 2.3.0，stable 全量）

- 仓库**无任何 lint/type 配置**（无 pyproject/setup.cfg/ruff/mypy/pyright）。
- ruff：**1191 项**（tests 343 / 非 tests 848；62.5% 可自动修复）。
  Top：UP006 211、I001 162、UP045 154、BLE001 135、F401 87、RUF100 79、
  S110 35、SIM117 33、TRY004 25、DTZ 19、RUF012 11（可变类属性默认值）。
- 真实代码可疑项（非测试，仅 3 项）：`astock.py:63` B023 闭包未绑定循环变量
  （需人工确认）；`northbound_capital_flow.py:151` F841 死变量；无 F821
  （undefined name）。
- mypy：**212 错误 / 56 文件**（`--ignore-missing-imports --follow-imports=skip`，
  0 条缺 import 噪音）。重灾区：myreports.py（30）、technical_indicators.py（23）；
  主要类别：arg-type 61、operator 57、union-attr 23、assignment 20。
- migration cost：ruff 门控 1–2 人日（建议先 `--fix` 自动修 + BLE001 策略化）；
  mypy 门控 2–4 人日（按文件分批收口或新增代码门控）。

### TypeScript / frontend

- tsconfig：`strict: true` + noUnusedLocals/Parameters + moduleResolution bundler。
- `tsc --noEmit`：**0 错误**（411 输入文件 / 244 src 源文件）。
- **ESLint：不存在**（无依赖、无配置、无脚本）——TS 侧最大治理缺口，但
  strict tsc 已覆盖大部分类型安全；ESLint 建议为 OPTIONAL/FUTURE。

## 7. REL-06 密钥与敏感数据扫描

- 高危模式（私钥/sk-/gh[pousr]_/AKIA/JWT/URL 内嵌凭据）：**0 命中**。
- 关键词 118 命中/40 文件，全部判定安全：泄漏防护测试夹具（"sk-secret" 假值 +
  断言）、环境变量引用、`secrets.token_hex(32)` 标准库、文档提及。
- **P3**：`backend/gstock.py:103` 硬编码 `"token": "D43BF722..."`（东财
  searchapi **公开端点常量**，公开文档广泛记载、非个人账户凭据）→ 建议日后
  移入配置，不构成泄漏。
- tracked 敏感文件：仅 `backend/.env.example`（空模板）；无 .env/.sqlite/.db/
  portfolio.json/account_profile.json/.pem/.key 进入 Git。

## 8. REL-07 干净复现实验

- 环境：Python 3.12.10 + pip 26.2.1；Node 26.4.0 + npm 11.17.0；全部 %TEMP%
  隔离目录（未复用任何本地 site-packages）。
- Python 干净安装 51.5s（60 包，含 numpy 2.5.1/tdxpy/curl_cffi/lxml 等）；
  全量离线测试 **3391 passed / 0 failed / 11 deselected**（108.9s）。
- frontend 干净 `npm ci`：249 包、~20s、无 integrity 错误。
- **回答：可以重建并通过核心离线验证**（当前版本组合下）；但 Python 侧
  "重建出什么版本"不可复现（无 lock），这正是 REL-01 的核心债。
- 观察：backend 测试按 repo 根相对路径加载 `docs/research/BK11_*_FIXTURE_V01.json`
  （首轮提取口径缺失导致 137 失败，补齐后全绿）——测试与 docs/research
  存在隐式耦合，记 P3。

## 9. REL-08 工程债务矩阵

| # | finding | severity | evidence | actual impact | trigger | confirmed/theoretical | recommended fix | blast radius | phase |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Python 依赖无 lock，不可复现 | **P1** | REL-01：全树零 lock；60 包现场解析；CI 3.11 vs 本地 3.12 | 上游发版即漂移；CI 失败无法回溯；安全审计无版本证据 | 每次 pip install | confirmed | pip-tools `requirements.lock` + CI 装 lock；对齐解释器版本 | 低（构建/CI 层） | 实现阶段第一批 |
| 2 | Node 20 弃用警告（checkout@v4/setup-node@v4） | P2 | REL-03：run 日志 deprecation warning | 未来 Actions 强制 Node 24 后旧版本失效 | Actions 运行时 | confirmed | 升级 @v5（验证存在性） | 低 | 实现阶段 |
| 3 | thesis E2E intermittent（UI 可见性时序） | **P2** | 1/30 flake；exact head 复跑成功 | CI 偶发红，需要人工 rerun | 偶发 | confirmed | 稳定性加固（等待策略/selector）专项 | 中 | 专项 |
| 4 | backend 测试 threading 竞态 flake | P2 | run 31071803129 attempt1 失败/attempt2 成功 | 同上 | 偶发 | confirmed | 测试等待原语修正 | 低 | 实现阶段 |
| 5 | Python 静态基线零配置（ruff 1191 / mypy 212） | P2 | REL-05 | 风格/类型债务累积；mypy 中 arg-type/operator 57 项含潜在真实错误 | 持续 | confirmed | 先修后门控：ruff（1-2 人日）→ mypy（2-4 人日，按文件） | 中 | 实现阶段 |
| 6 | 前端无 ESLint | P3 | REL-05 | 无 hooks/unsafe 规则网；tsc strict 已覆盖大部分 | — | confirmed | 可加 changed-files-only 基线 | 中 | FUTURE/LOW ROI 边缘 |
| 7 | 3 个 npm high（postcss/react-router） | P3 | REL-02 | 生产不可达（无 Node 运行时） | 仅构建期 | confirmed | 随常规升级处理；不紧急 | 低 | 随升级 |
| 8 | gstock.py 公开 token 常量硬编码 | P3 | REL-06 | 无泄漏（公开常量）；维护性 | — | confirmed | 移入配置 | 低 | 顺手 |
| 9 | tests 依赖 docs/research fixture 路径 | P3 | REL-07 首轮 137 失败 | 提取/打包口径敏感 | 非仓库内运行 | confirmed | fixture 路径固化或复制到 tests 下 | 低 | 顺手 |
| 10 | SHA pin / runner pin / cache 隔离 | — | REL-03 | 单人私有仓库无实际攻击面 | — | theoretical | 不实施 | — | **LOW_ROI** |
| 11 | uv lock 整套工具链 | — | REL-01 | pip-tools 已够 | — | — | 不采用 | — | **LOW_ROI/OVER_ENGINEERED** |
| 12 | 企业级 supply-chain 模板（Dependabot/SCA 门禁等） | — | REL-03 | 单人项目无多贡献者 | — | — | 不实施 | — | **LOW_ROI/OVER_ENGINEERED** |

## 10. 若只能修三件事

1. Python 依赖锁（pip-tools requirements.lock + CI 安装 lock + 解释器版本对齐）——P1；
2. Actions 升级（checkout/setup-node @v5，消除 Node 20 弃用 RISK）——P2 最快闭环；
3. ruff 基线（先修后门控，1–2 人日收敛 1191 项）——P2 最高性价比。

## 11. 下一阶段建议

**Engineering Reliability Implementation v0.1**（Phase B，待授权）：
按上表 1→2→3→4→5 顺序实施；mypy 与 ESLint 采用 baseline/changed-files-only
策略而非全仓清零；thesis E2E 稳定性另立专项。本阶段不改业务功能。

---

## 12. Phase B1 实施结果（2026-08-08，已落地于
`chore/python-dependency-reproducibility-v0.1`）

- 工具：pip-tools **7.6.0**（钉于 `backend/requirements-tooling.txt`）；
  编译 authority = CPython **3.11.15**（uv 获取）。
- lock 拓扑：`requirements.lock.txt`（53 包）+ `requirements-dev.lock.txt`
  （58 包，自包含单文件，无 `-r` 引用）。
- **Contract B（Canonical Lock + Compatibility Runtime）**：LOCK_AUTHORITY =
  Ubuntu/3.11（权威 lock 需在 CI 平台重生成以纳入 uvloop pin）；Windows/3.12 =
  COMPATIBILITY_TESTED / NOT_LOCK_AUTHORITY。
- **LOCKING_CURRENT_RESOLUTION**：与 Phase A 解析完全一致
  （fastapi 0.141.1 / pandas 3.0.5 / pytest 9.1.1 / numpy 2.4.6 等），
  未升级任何 direct dependency。
- hashes：提交形态不带（Linux `--require-hashes` 因 uvloop extra 硬失败）；
  权威平台生成后可启用。
- Reproducibility Proof：两个全新独立 3.11 环境 freeze 零差异；3.12 版本层
  一致；pytest `-m "not live"`：3.11 与 3.12 均 **1823 passed / 0 failed /
  11 deselected（108s / 104s）——该口径为子任务环境自报值；主 Agent 复测
  collect-only 确认为 **3391 collected / 11 deselected**（backend 目录、
  CI 等价口径），与 §8 全量口径一致，以 3391 为准。
- CI：4 个 Python job 改为 `pip install -r backend/requirements-dev.lock.txt`，
  `cache-dependency-path` 指向 lock。
- 待办（发布轮）：Linux CI 重生成权威 lock（纳入 uvloop）→ 可选启用 hashes；
  Node actions 弃用警告留 Phase B2。

### 12.1 Contract B 修正（2026-08-08，Platform-Specific Lock Closure 轮）

- **Contract B 已被实证否定**：single cross-platform lock 不可行（uvloop 无
  Windows wheel，Windows 全新环境安装 canonical Linux lock 实测失败：
  `RuntimeError: uvloop does not support Windows`；tzdata/mini-racer/
  colorama 为 Windows-only、akracer 为 Linux-only）。
- **最终合同 = CONTRACT D（PLATFORM-SPECIFIC AUTHORITATIVE LOCKS）**：
  - Linux / CPython 3.11 = EXACT REPRODUCIBLE（CI authority）
  - Windows / CPython 3.12.10 = EXACT REPRODUCIBLE LOCAL DEVELOPMENT
    （本机 authority）
- Lock 拓扑：`requirements-linux-py311.lock.txt`（53 包）+
  `requirements-dev-linux-py311.lock.txt`（58 包）+
  `requirements-dev-windows-py312.lock.txt`（Windows dev 完整 closure，
  无第四份 Windows runtime lock——Windows 非生产目标，DRY）。
- Windows lock 由 Windows/3.12.10 + pip 26.0.1 + pip-tools 7.6.0 生成并
  实证编译幂等；CI 新增 `windows-lock-check` job（windows-latest/3.12.10）
  验证再生成零 diff + 干净安装 + 离线测试。

> **作废标注**：本节 §12 正文中出现的旧文件名 `requirements.lock.txt` 与
> `requirements-dev.lock.txt`（Contract B 阶段命名）已于 Contract D 轮
> **重命名为 `requirements-linux-py311.lock.txt` / `requirements-dev-linux-py311.lock.txt`**
> 并删除旧名；上述旧名仅在历史叙述中出现，当前仓库不存在同名文件。
