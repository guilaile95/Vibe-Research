# PR #278 研究摘要修正 — 修改前后截图证据

全部为隔离合成数据（临时 VR_DATA_DIR + 独立端口 + Chromium headless）真实渲染截图。

| 文件 | head | 场景 | 证明内容 |
| --- | --- | --- | --- |
| research-brief-disproven-before.png | `753e190`（修复前） | backend effective_state=DISPROVEN + 已确认证伪 delta | 旧 UI 仍显示「已确认冻结 v5」，全文无任何「已证伪」提示；重复的「确认版本」格与「Current Thesis」格显示同一文案 |
| research-brief-disproven-after.png | 本 PR | 同一 DISPROVEN fixture | 红色终态横幅、当前确认状态=已证伪、最初冻结观点标注历史原貌、已确认变更（含确认时间 / 基线版本 / 可展开反对依据及来源）、比较基线与读取时间溯源 |
| research-brief-after.png | 本 PR | WEAKENED（不终止研究）+ 有来源支持/反对依据 | 削弱徽标、ready=true 诚实说明、更新分区、变化区基线溯源；随后 Preview→显式确认→Commit 全流程通过 |
| research-brief-fallback.png | 本 PR | Current Thesis identity 校验失败 | 上下文校验失败时不输出 CONFIRMED、不展示该对象证据与失效条件，gaps 明确列出 identity 不一致 |

生成脚本：`frontend/tests/e2e/decision-commit-vertical.browser.mjs`（默认 / BRIEF_SCENARIO=disproven / DF2_FORCE_CONTEXT_FALLBACK=1）；
修改前截图由一次性本地脚本在 `753e190` 旧 dist 上生成（未提交）。合并时可整体删除本目录。
