import assert from 'node:assert/strict';

// Deliberately synthetic, including unsupported identifiers. Never open a real portfolio file.
export function portfolioEntryFixture(authority) {
  return {
    holding_authority: authority,
    holdings: ['600519', '00700', 'AAPL', '005930.KS'].map(code => ({
      code, name: `合成持仓 ${code}`, price: 10, shares: 100, cost: 8,
      market_value: 1000, pnl: 200, pnl_pct: 25,
    })),
    totals: { market_value: 4000, cost: 3200, pnl: 800, pnl_pct: 25 },
    closed: [], realized_pnl: 0, updated: 'Synthetic fixture', last_refresh: null,
  };
}

export async function checkPortfolioEntries(page, { baseURL, width, output, setAuthority, phase, writes, storageWrites }) {
  for (const authority of ['LEGACY_PORTFOLIO', 'LEDGER_DERIVED']) {
    setAuthority(authority);
    await phase(`portfolio-entry-${authority}`);
    await page.goto('/portfolio');
    const row = page.locator('#portfolio-holding-600519');
    await row.waitFor();
    assert.equal(await row.getByTitle('编辑', { exact: true }).count(), authority === 'LEGACY_PORTFOLIO' ? 1 : 0);
    assert.equal(await row.getByTitle('删除', { exact: true }).count(), authority === 'LEGACY_PORTFOLIO' ? 1 : 0);
    const valuesBefore = await row.locator('td').allTextContents();
    for (const code of ['00700', 'AAPL', '005930.KS']) {
      const unsupported = page.locator('tr').filter({ hasText: `合成持仓 ${code}` });
      assert.equal(await unsupported.locator('a').count(), 0, `unsupported ${code} stays display-only`);
    }
    if (authority === 'LEGACY_PORTFOLIO') {
      await row.getByTitle('编辑', { exact: true }).click();
      const editor = page.getByRole('heading', { name: '编辑持仓', exact: true }).locator('..');
      assert.deepEqual(await editor.locator('input').evaluateAll(nodes => nodes.map(node => node.value)), ['600519', '100', '8']);
      await editor.getByRole('button', { name: '取消', exact: true }).click();
      assert.deepEqual(await row.locator('td').allTextContents(), valuesBefore);
    }
    const expectedReturn = '/portfolio#portfolio-holding-600519';
    const data = row.getByRole('link', { name: '查看数据', exact: true });
    const research = row.getByRole('link', { name: '候选研究', exact: true });
    for (const entry of [data, research]) {
      const target = new URL(await entry.getAttribute('href'), baseURL);
      assert.equal(target.searchParams.get('return_to'), expectedReturn);
      for (const key of ['campaign', 'campaign_id', 'question', 'round', 'action', 'create', 'strategy']) assert.equal(target.searchParams.has(key), false);
      assert.ok((await entry.boundingBox()).height >= 44, 'keyboard/touch target remains usable');
    }
    await data.focus(); await data.press('Enter');
    await page.getByRole('heading', { name: '个股数据', exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('code'), '600519');
    await page.getByTestId('stock-data-sector-return').click(); await row.waitFor();
    assert.equal(new URL(page.url()).pathname + new URL(page.url()).hash, expectedReturn);
    await research.focus(); await research.press('Enter');
    await page.getByTestId('candidate-workspace').waitFor();
    assert.equal(new URL(page.url()).pathname, '/candidates/600519');
    assert.equal(await page.getByTestId('candidate-workspace').getAttribute('data-security-code'), '600519');
    assert.equal(await page.locator('input[type="radio"]:checked').count(), 0, 'no strategy is preselected');
    await page.goBack(); await row.waitFor();
    await page.goForward(); await page.getByTestId('candidate-workspace').waitFor();
    await page.getByTestId('candidate-stock-data-entry').click(); await row.waitFor();
    assert.equal(new URL(page.url()).pathname + new URL(page.url()).hash, expectedReturn);
    assert.deepEqual(await row.locator('td').allTextContents(), valuesBefore, 'navigation leaves holding values/actions untouched');
    await storageWrites.flush(page);
    assert.deepEqual(writes, [], 'holding navigation has no API writes or model calls');
    assert.deepEqual(storageWrites.filter(event => event.kind !== 'navigation-preference'), [], 'holding navigation has no research/note writes');
    await row.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${output}/portfolio-entry-${authority}-${width}.png` });
  }
}
