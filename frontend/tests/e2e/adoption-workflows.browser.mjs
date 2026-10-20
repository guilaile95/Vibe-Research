/** Bounded synthetic DOM acceptance of six production components, not live-provider,
 * backend persistence, full EvidenceDetail navigation, or whole-app acceptance.
 * node --import ./tests/e2e/runtime-env.mjs tests/e2e/adoption-workflows.browser.mjs
 * Add --build-only to compile without opening a socket or launching Chromium.
 * Optional E2E_ARTIFACT_DIR writes real screenshots and route audit only after a run.
 */
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, preview } from 'vite';
import { chromium } from 'playwright';
import { syntheticApi } from './fixtures/adoption-api.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
// Tailwind resolves its config from cwd, as do existing frontend scripts.
process.chdir(root);
const outDir = await mkdtemp(path.join(tmpdir(), 'adoption-workflows-'));
await build({ root, build: { outDir, rollupOptions: { input: path.join(root, 'tests/e2e/fixtures/adoption-workflows.html') } } });
if (process.argv.includes('--build-only')) {
  console.log('Fixture build passed. Actual-browser acceptance: NOT_EVALUATED (build-only).');
} else {
  let browser, server;
  const { state, dispatch } = syntheticApi();
  const violations = [], pageErrors = [];
  const artifacts = process.env.E2E_ARTIFACT_DIR;
  try {
    if (artifacts) await mkdir(artifacts, { recursive: true });
    server = await preview({ root, build: { outDir }, preview: { host: '127.0.0.1', port: 0, strictPort: false } });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, timezoneId: 'UTC', serviceWorkers: 'block' });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => pageErrors.push(error.message));
    await context.routeWebSocket('**/*', socket => { violations.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { violations.push(`${req.method()} ${url}`); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) {
        if (req.method() === 'GET' && (/^\/assets\/[^/]+\.(js|css)$/.test(url.pathname) || url.pathname === '/tests/e2e/fixtures/adoption-workflows.html' || url.pathname === '/favicon.ico')) return route.continue();
        violations.push(`${req.method()} ${url.pathname}`); return route.abort();
      }
      try {
        const result = dispatch(req.method(), url, req.postData() ? req.postDataJSON() : undefined);
        if (result?.errorStatus) return route.fulfill({ status: result.errorStatus, json: { detail: result.detail } });
        return route.fulfill({ json: { data: result } });
      } catch (error) { violations.push(error.message); return route.abort(); }
    });
    const shown = async locator => locator.waitFor({ state: 'visible' });
    const nav = async name => page.getByRole('button', { name, exact: true }).click();
    const layout = async name => {
      for (const width of [1280, 375]) {
        await page.setViewportSize({ width, height: 900 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${name}: ${width}px document overflow`);
        if (artifacts) await page.screenshot({ path: path.join(artifacts, `synthetic-${name}-${width}.png`), fullPage: true });
      }
      await page.setViewportSize({ width: 1280, height: 900 });
    };
    await page.goto(`${origin}/tests/e2e/fixtures/adoption-workflows.html`);

    // Manual DCF: HTML-required empty state, exact-input receipt and invalidation.
    const dcf = page.getByTestId('reverse-dcf');
    await dcf.locator('summary').click();
    await dcf.getByRole('button', { name: '计算价格隐含增长率', exact: true }).click();
    assert.equal(state.calls.length, 0, 'empty DCF must not submit');
    await dcf.getByLabel('行业适用性').selectOption('non_financial');
    await dcf.getByLabel('行业分类来源').fill('Synthetic filing');
    for (const label of ['参考股价', '年度无杠杆自由现金流 FCFF', '净债务（债务减现金，可为负）', '稀释后股数']) {
      const field = dcf.locator('fieldset').filter({ has: page.locator('legend', { hasText: label }) }).filter({ has: page.getByLabel(`${label}数值`, { exact: true }) }).last();
      await field.getByLabel(`${label}数值`, { exact: true }).fill('100');
      if (label !== '稀释后股数') await field.getByLabel('币种', { exact: true }).selectOption('CNY');
      await field.getByLabel('来源（报告/页码或链接）').fill('Synthetic page 1');
      await field.getByLabel('数据截至日').fill('2026-01-06');
    }
    await dcf.getByLabel('FCF 口径', { exact: true }).selectOption('annual_unlevered_fcff');
    for (const [label, value] of [['WACC (%)，0 至 100','10'], ['永续增长率 (%)，大于 -100，最高 20','2'], ['显式预测年数（整数 1–30）','5'], ['求解增长率下界 (%)，大于 -100','-50'], ['求解增长率上界 (%)，最高 300','50'], ['敏感性 WACC (%)，逗号分隔，最多 9 个','9,11'], ['假设依据与局限','Synthetic only']]) await dcf.getByLabel(label, { exact: true }).fill(value);
    await dcf.getByRole('button', { name: '计算价格隐含增长率', exact: true }).click();
    await shown(dcf.getByTestId('reverse-dcf-result'));
    assert.match(await dcf.getByTestId('reverse-dcf-result').innerText(), /5.00%/);
    await dcf.getByLabel('参考股价数值', { exact: true }).fill('101');
    assert.equal(await dcf.getByTestId('reverse-dcf-result').count(), 0);
    state.wrongDcf = true;
    await dcf.getByRole('button', { name: '计算价格隐含增长率', exact: true }).click();
    await shown(dcf.getByRole('alert'));
    assert.match(await dcf.getByRole('alert').innerText(), /回执与输入不一致/);
    await nav('Switch subject');
    await shown(dcf.getByLabel('参考股价数值', { exact: true }));
    assert.equal(await dcf.getByLabel('参考股价数值', { exact: true }).inputValue(), '');
    assert.equal(await dcf.getByRole('alert').count(), 0);
    await nav('Switch subject');
    await layout('dcf');

    // Actual EvidenceDetail child: append versions, preserved text and compare.
    await nav('filing');
    const filing = page.getByRole('region', { name: '原始文档证据与章节比较' });
    await shown(filing.getByText('原始文档不可用', { exact: false }));
    for (let version = 1; version <= 2; version++) {
      await filing.getByRole('button', { name: '登记用户原文', exact: true }).click();
      assert.equal(await filing.getByRole('button', { name: '确认保存未核验原文' }).isDisabled(), true);
      await filing.getByLabel('来源文档身份（如本地文件名/登记编号）', { exact: true }).fill('synthetic.txt');
      await filing.getByLabel('版本标识', { exact: true }).fill(`v${version}`);
      await filing.getByLabel('来源标题', { exact: true }).fill(`Synthetic filing ${version}`);
      await filing.getByLabel('原文', { exact: true }).fill(`Revenue  ${version}00\n<script>not executable</script>`);
      if (version === 2) await filing.getByLabel('更正旧版本', { exact: true }).selectOption('doc-1');
      await filing.getByRole('button', { name: '确认保存未核验原文' }).click();
      await shown(filing.getByText(`Synthetic filing ${version} · 10-K · 000001 · v${version}`, { exact: true }));
    }
    assert.match(await filing.innerText(), /更正版本，原版本保留：doc-1/);
    await filing.getByRole('button', { name: '查看保留原文与章节' }).first().click();
    await shown(filing.getByRole('button', { name: '关闭原文' }));
    assert.equal(await filing.locator('pre').innerText(), 'Revenue  100\n<script>not executable</script>');
    await filing.getByLabel('旧文档', { exact: true }).selectOption('doc-1');
    await filing.getByLabel('新文档', { exact: true }).selectOption('doc-2');
    await filing.getByRole('button', { name: '比较原文差异' }).click();
    await shown(filing.getByLabel('原文差异结果'));
    assert.match(await filing.getByLabel('原文差异结果').innerText(), /Revenue  200/);
    await filing.getByLabel('新文档', { exact: true }).selectOption('doc-1');
    assert.equal(await filing.getByRole('button', { name: '比较原文差异' }).isDisabled(), true);
    assert.equal(await filing.getByLabel('原文差异结果').count(), 0);
    await layout('filing');

    // Chart keyboard selects exact bar; appended note readback and stale rejection.
    await nav('annotation');
    await page.getByTestId('kline-inspection-control').focus();
    await page.keyboard.press('Home');
    await nav('手工研究标注');
    const notes = page.getByRole('region', { name: '持久研究标注' });
    await shown(notes.getByText('此股票尚无已读取的标注。', { exact: true }));
    assert.equal(await notes.getByRole('button', { name: '追加保存标注' }).isDisabled(), true);
    await notes.getByLabel('笔记（最多 2000 字）').fill('Synthetic selected-bar note');
    await notes.getByRole('button', { name: '追加保存标注' }).click();
    await shown(notes.getByTestId('research-annotation'));
    assert.match(await notes.getByTestId('research-annotation').innerText(), /2026-01-05.*本快照精确日期匹配/);
    assert.equal(await notes.getByText('MUST NOT DISPLAY WRONG SUBJECT').count(), 0);
    state.failAnnotation = true;
    await notes.getByLabel('笔记（最多 2000 字）').fill('Preserve stale draft');
    await notes.getByRole('button', { name: '追加保存标注' }).click();
    await shown(notes.getByRole('alert'));
    assert.equal(await notes.getByLabel('笔记（最多 2000 字）').inputValue(), 'Preserve stale draft');
    assert.equal(state.notes.length, 1);
    await layout('annotation');

    // Register and append resolution through real forms; no outcome is not zero score.
    await nav('prediction');
    const journal = page.getByTestId('prediction-journal');
    await journal.locator(':scope > summary').click();
    await shown(journal.getByText('Brier（0–1', { exact: false }));
    assert.match(await journal.innerText(), /Brier（0–1[^\n]+不可用/);
    await journal.getByLabel('对象 / Thesis 引用（自报文本）', { exact: true }).fill('Synthetic subject');
    await journal.getByLabel('明确的二元问题与判定标准', { exact: true }).fill('Synthetic binary outcome?');
    await journal.getByLabel('事前证据背景 / 来源引用', { exact: true }).fill('Synthetic preregistration');
    await journal.getByLabel('成立概率（%，0–100）', { exact: true }).fill('70');
    await journal.getByLabel('未来截止时间（本机时区）', { exact: true }).fill('2030-01-01T00:00');
    await journal.getByRole('checkbox').check();
    await journal.getByRole('button', { name: '锁定预测到本地归档' }).click();
    await shown(journal.getByText('原预测已锁定；后续只能追加结果修订', { exact: true }));
    const record = journal.locator('article');
    assert.match(await record.innerText(), /未决 · 结果修订 0/);
    await record.getByText('追加人工结果 / 修正（不重写原预测）', { exact: true }).click();
    await record.getByLabel('结果', { exact: true }).selectOption('TRUE');
    await record.getByLabel('结果证据可用时间（本机时区）', { exact: true }).fill('2030-01-02T00:00');
    await record.getByLabel('依据', { exact: true }).fill('Synthetic resolution evidence');
    await record.getByLabel('首次判定说明 / 修正原因', { exact: true }).fill('Synthetic determination');
    await record.getByRole('button', { name: '追加结果修订' }).click();
    await shown(journal.getByText('人工结果修订已追加，原记录保留', { exact: true }));
    assert.match(await journal.innerText(), /0.0900/);
    await journal.getByLabel('历史可见时间（本机时区；留空看当前）', { exact: true }).fill('2031-01-01T00:00');
    await shown(journal.getByText('历史视图只含', { exact: false }));
    assert.equal(await journal.getByRole('button', { name: '锁定预测到本地归档' }).isDisabled(), true);
    assert.equal(await record.getByRole('button', { name: '追加结果修订' }).isDisabled(), true);
    await layout('prediction');

    // Explicit allocation targets, rejected duplicate, unknown target and expiry.
    await nav('allocation');
    const allocation = page.getByTestId('allocation-target-card');
    await shown(allocation.getByText('尚未配置目标；没有默认目标组合', { exact: true }));
    await allocation.getByRole('button', { name: '配置目标', exact: true }).click();
    await allocation.getByLabel('目标生效日期', { exact: true }).fill('2026-01-01');
    await allocation.getByLabel('配置目标百分比', { exact: true }).fill('000001 40\n000001 20');
    await allocation.getByRole('button', { name: '保存新目标版本' }).click();
    await shown(allocation.getByRole('alert'));
    assert.equal(state.versions.length, 0);
    await allocation.getByLabel('配置目标百分比', { exact: true }).fill('000001 40');
    await allocation.getByRole('button', { name: '保存新目标版本' }).click();
    await shown(allocation.getByText('生效版本 1', { exact: false }));
    assert.match(await allocation.innerText(), /偏离 \+10.00 pp/);
    assert.match(await allocation.innerText(), /目标 未知/);
    assert.deepEqual(state.versions[0].input.targets, { '000001': 40 });
    state.expireAllocation = true;
    await allocation.getByRole('button', { name: '刷新比较' }).click();
    await shown(allocation.getByText('比较已过期，请刷新；旧实际占比和偏离已隐藏', { exact: true }));
    assert.doesNotMatch(await allocation.innerText(), /\+10.00 pp/);
    await layout('allocation');

    // Explicit manual announcement relation, declaration gate and readback.
    await nav('groups');
    const groups = page.getByRole('region', { name: '公告中心用户关联' });
    await shown(groups.getByText('手动登记关联', { exact: true }));
    await groups.getByText('手动登记关联', { exact: true }).click();
    await groups.getByLabel('报告期 / 事件范围', { exact: true }).fill('Synthetic FY2026');
    await groups.getByLabel('同一个股的另一条证据', { exact: true }).selectOption('commentary');
    await groups.getByLabel('关系', { exact: true }).selectOption('commentary');
    assert.equal(await groups.getByRole('button', { name: '保存用户关联' }).isDisabled(), true);
    await groups.getByRole('checkbox').check();
    await groups.getByRole('button', { name: '保存用户关联' }).click();
    await shown(groups.getByText('用户声明范围：Synthetic FY2026 · 2 条证据 · 修订 1', { exact: true }));
    assert.match(await groups.innerText(), /用户标注评论\/报道/);
    assert.match(await groups.innerText(), /未验证为同一事件/);
    await layout('groups');
    await nav('Switch subject');
    await shown(groups.getByText('手动登记关联', { exact: true }));
    assert.equal(await groups.getByText('用户声明范围：Synthetic FY2026', { exact: false }).count(), 0);

    // Audit includes reads after every accepted write and rejects all other API paths.
    for (const [method, path, readPath] of [['POST','/filing-evidence/documents/anchor','/filing-evidence/context/anchor'], ['POST','/research-annotations','/research-annotations'], ['POST','/prediction-journal','/prediction-journal'], ['PUT','/portfolio/allocation-targets','/portfolio/allocation-targets'], ['POST','/announcement-groups','/announcement-groups/context/anchor']]) {
      const writeIndex = state.calls.findIndex(c => c.method === method && c.path === path);
      assert.ok(writeIndex >= 0 && state.calls.slice(writeIndex+1).some(c => c.method === 'GET' && c.path === readPath), `${path} must read back`);
    }
    assert.deepEqual(violations, [], 'unexpected network/route attempts');
    assert.deepEqual(pageErrors, [], 'browser errors');
    console.log('PASS: six synthetic production-component browser workflows; no live-provider or full-app evidence');
  } finally {
    if (artifacts) await writeFile(path.join(artifacts, 'synthetic-route-audit.json'), JSON.stringify({ calls: state.calls, violations, pageErrors }, null, 2));
    await browser?.close();
    if (server) await new Promise(resolve => server.httpServer.close(resolve));
  }
}
