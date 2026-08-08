# Pull Request（个人项目最小模板）

## 变更范围

- 功能/修复：
- 主要文件：

## 验证证据（必须真实填写；未运行就写"未运行"）

- [ ] 后端离线测试：`pytest backend -m "not live"` → 结果
- [ ] 前端：`npm test` → 结果；`npm run build` → 结果
- [ ] E2E（如涉及 UI）：`npm run test:e2e:<suite>` → 结果
- [ ] 未触碰：稳定分支、生产数据、密钥/Token
- [ ] 基于当前稳定 Head：`git rev-parse origin/feature/research-system-v01`

## 说明

- Draft 状态下不得 Ready/merge；CI 未全绿（含 GitHub billing 阻断）时保持 Draft。
- 本 PR 不解决：（如适用，列出明确排除项）
