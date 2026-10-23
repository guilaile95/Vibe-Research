// Rendered production UI only; called by research-check-loop's existing CI gate.
// Reuses its disposable saved Q2/R2 and write audit. No backend or model is used.
import assert from 'node:assert/strict';

const localHref = page => { const url = new URL(page.url()); return url.pathname + url.search + url.hash; };
const claimPlaceholder = '一句话陈述这条证据说了什么。例如：公司2024Q3营收同比+25%，超出市场一致预期+18%。';

export async function checkStockEvidenceReturns({ page, question, round, candidateHref, waitForSelection, readDatabase, storageWrites, onWrite }) {
  const initialDatabase = await readDatabase(page), initialWrites = storageWrites.length;
  const writes = [], checks = [];
  let savingType = null;
  const routePattern = /\/api\/(valuation|announcements|news|evidence)(?:\?|$)/;
  const handler = async route => {
    const request = route.request(), url = new URL(request.url());
    const code = url.searchParams.get('code');
    if (request.method() === 'GET') {
      const data = url.pathname === '/api/valuation' ? { code, name: '合成资料公司', price: 10 }
        : url.pathname === '/api/announcements' ? [{ title: '合成公告', date: '2026-10-22', url: 'https://example.org/synthetic-announcement' }]
        : url.pathname === '/api/news' ? [{ 新闻标题: '合成新闻', 发布时间: '2026-10-22 09:00:00', 新闻链接: 'https://example.org/synthetic-news' }] : null;
      return data ? route.fulfill({ json: { data } }) : route.fallback();
    }
    if (url.pathname !== '/api/evidence') return route.fallback();
    const body = request.postDataJSON();
    const event = { method: request.method(), path: url.pathname, body, savingType };
    writes.push(event); onWrite(event);
    assert.equal(request.method(), 'POST');
    assert.ok(savingType, 'navigation must never create evidence');
    assert.equal(body.evidence_type, savingType);
    assert.equal(body.subject_id, question.securityCode);
    return route.fulfill({ json: { data: { ...body, id: `synthetic-capture-${savingType}`, created_at: '2026-10-23T00:00:00Z' } } });
  };
  await page.route(routePattern, handler);
  const captureLink = type => page.locator(`[data-testid="stock-data-capture-evidence"][href*="evidence_type=${type}"]`);
  const openCapture = async (type, stockHref) => {
    // Tabs are component state, not a persisted navigation promise. Reopen events.
    await page.getByTestId('stock-data-tab-events').click();
    await captureLink(type).waitFor();
    const target = new URL(await captureLink(type).getAttribute('href'), page.url());
    assert.equal(target.searchParams.get('return_to'), stockHref);
    await captureLink(type).click();
    await page.getByRole('heading', { name: '新建证据', exact: true }).waitFor();
    assert.equal(await page.getByPlaceholder('如 600519 / humanoid / AI算力').inputValue(), new URL(stockHref, page.url()).searchParams.get('code'));
  };
  const returnedToStock = async stockHref => {
    await page.getByTestId('stock-data-candidate-entry').waitFor();
    assert.equal(localHref(page), stockHref);
  };
  const openSaved = async () => {
    await page.goto(candidateHref);
    await waitForSelection(page, question.id, round.id, round.judgement);
  };
  try {
    for (const type of ['announcement', 'news']) {
      await openSaved();
      const stableCandidate = localHref(page);
      let stableStock;
      // Both product actions and browser history must preserve the saved identity.
      for (const action of ['cancel', 'return', 'browser-back', 'dirty-cancel', 'cancel']) {
        const before = writes.length;
        await page.getByTestId('candidate-open-stock-data').click();
        await page.getByTestId('stock-data-candidate-entry').waitFor();
        const stockHref = localHref(page);
        stableStock ??= stockHref;
        assert.equal(stockHref, stableStock, 'five loops cannot grow nested return_to URLs');
        await openCapture(type, stockHref);
        if (action === 'dirty-cancel') {
          await page.getByPlaceholder(claimPlaceholder).fill('合成未保存修改');
          await page.getByRole('link', { name: '取消', exact: true }).click();
          const dialog = page.getByRole('dialog', { name: '内容尚未保存', exact: true });
          await dialog.waitFor();
          await dialog.getByRole('button', { name: '留在此页', exact: true }).click();
          assert.equal(await page.getByPlaceholder(claimPlaceholder).inputValue(), '合成未保存修改');
          await page.getByRole('link', { name: '取消', exact: true }).click();
          await dialog.getByRole('button', { name: '放弃未保存内容并离开', exact: true }).click();
        } else if (action === 'browser-back') {
          await page.goBack();
          await returnedToStock(stockHref);
          await page.goForward();
          await page.getByRole('heading', { name: '新建证据', exact: true }).waitFor();
          await page.goBack();
        } else {
          await page.getByRole('link', { name: action === 'return' ? '返回' : '取消', exact: true }).click();
        }
        await returnedToStock(stockHref);
        assert.equal(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), stableCandidate);
        await page.getByTestId('stock-data-candidate-entry').click();
        await waitForSelection(page, question.id, round.id, round.judgement);
        assert.equal(localHref(page), stableCandidate);
        assert.equal(writes.length, before, `${type} ${action} is read-only`);
        checks.push(`${type}:${action}:Q2/R2`);
      }
      await page.getByTestId('candidate-open-stock-data').click();
      await page.getByTestId('stock-data-candidate-entry').waitFor();
      const stockHref = localHref(page), beforeSave = writes.length;
      await openCapture(type, stockHref);
      savingType = type;
      await page.getByRole('button', { name: '保存', exact: true }).click();
      await returnedToStock(stockHref);
      savingType = null;
      assert.equal(writes.length - beforeSave, 1, 'each explicit save creates exactly one Evidence POST');
      await page.getByTestId('stock-data-candidate-entry').click();
      await waitForSelection(page, question.id, round.id, round.judgement);
      checks.push(`${type}:explicit-save:one-POST:Q2/R2`);
    }

    for (const upstream of [null, '//evil.example', 'https://evil.example', '/%255cevil.example']) {
      const params = new URLSearchParams({ code: question.securityCode, view: 'synthetic' });
      if (upstream) params.set('return_to', upstream);
      const stockHref = `/stock-data?${params}#source-anchor`;
      for (const type of ['announcement', 'news']) {
        await page.goto(stockHref);
        await page.getByTestId('stock-data-candidate-entry').waitFor();
        await openCapture(type, stockHref);
        await page.getByRole('link', { name: '取消', exact: true }).click();
        await returnedToStock(stockHref);
        const candidateTarget = new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), page.url());
        assert.equal(candidateTarget.pathname, `/candidates/${question.securityCode}`);
        assert.equal(candidateTarget.searchParams.has('question'), false);
      }
    }
    checks.push('ordinary and hostile upstream: query/hash preserved, no false saved research');

    await openSaved();
    await page.getByTestId('candidate-open-stock-data').click();
    await page.getByTestId('stock-data-candidate-entry').waitFor();
    const query = page.getByPlaceholder('A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）', { exact: true });
    await query.fill('000001'); await query.press('Enter');
    await page.waitForFunction(() => document.querySelector('[data-active-code="000001"]'));
    const changedStock = localHref(page);
    for (const type of ['announcement', 'news']) {
      await openCapture(type, changedStock);
      await page.getByRole('link', { name: '取消', exact: true }).click();
      await returnedToStock(changedStock);
      const target = new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), page.url());
      assert.equal(target.pathname, '/candidates/000001');
      assert.equal(target.searchParams.has('question'), false);
      assert.equal(target.searchParams.has('round'), false);
    }
    checks.push('changed activeCode: both captures return to new stock without reconnecting Q2/R2');
    assert.equal(writes.length, 2);
    assert.deepEqual(await readDatabase(page), initialDatabase, 'capture, cancellation and explicit Evidence saves do not change saved research');
    await storageWrites.flush(page);
    assert.deepEqual(storageWrites.slice(initialWrites).filter(event => event.kind !== 'navigation-preference'), [], 'no question, round, operation or note writes');
    return { checks, writes };
  } finally {
    await page.unroute(routePattern, handler);
  }
}
