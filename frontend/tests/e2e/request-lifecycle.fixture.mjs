// Isolated synthetic API fixture. The existing navigation harness owns browser launch,
// origin isolation, widths, screenshots, and write auditing. No real provider calls.
import assert from 'node:assert/strict';
import { join } from 'node:path';
const deferred = () => { let resolve; const promise = new Promise(r => { resolve=r; }); return {promise,resolve}; };
const waitFor = async (predicate, message) => {
  for (let i=0; i<100; i++) { if(predicate()) return; await new Promise(r=>setTimeout(r,20)); }
  assert.ok(predicate(),message);
};
export async function checkRequestLifecycle(page, { baseURL, width, output }) {
  const reads=[], names=deferred(), oldPrimary=deferred();
  let mode='feed', failNews=false, holdOld=false, failKline=true;
  const handler = async route => {
    const req=route.request(), url=new URL(req.url()), path=url.pathname;
    if(url.origin!==baseURL || !path.startsWith('/api/')) return route.fallback();
    assert.equal(req.method(),'GET','read lifecycle must not mutate');
    reads.push({path,code:url.searchParams.get('code')});
    const ok=data=>route.fulfill({json:{data}}).catch(()=>{});
    if(path==='/api/watchlist') return ok({status:'valid',data:{codes:['600001','600002'],updated_at:null},etag:'1111111111111111'});
    if(path==='/api/quote') { if(mode==='feed') await names.promise; return ok({'600001':{name:'名称补齐'}}); }
    if(path==='/api/news') {
      if(failNews) return route.fulfill({status:503,json:{detail:'Synthetic unavailable'}});
      return ok([{新闻标题:'主资讯先展示 '+url.searchParams.get('code'),发布时间:'2026-10-23 10:00',新闻链接:''}]);
    }
    if(path==='/api/valuation') {
      if(holdOld && url.searchParams.get('code')==='600001') await oldPrimary.promise;
      return ok({code:url.searchParams.get('code'),name:'合成证券 '+url.searchParams.get('code'),price:10,pe_ttm:12,pb:1,mcap_yi:30,analyst_count:0});
    }
    if(path==='/api/finance') return ok({});
    if(path==='/api/kline') return failKline ? route.fulfill({status:503,json:{detail:'Synthetic unavailable'}}) : ok([]);
    return route.fulfill({status:503,json:{detail:'Synthetic unavailable source'}}).catch(()=>{});
  };
  await page.route('**/api/**',handler);
  try {
    await page.goto('/intel?tab=news');
    await page.getByText('主资讯先展示 600001',{exact:true}).waitFor();
    assert.match(await page.getByTestId('feed-coverage').innerText(),/成功 2 · 等待 0 · 失败 0/);
    assert.equal(await page.getByText('名称补齐',{exact:true}).count(),0,'code fallback renders before held optional names');
    await page.screenshot({path:join(output,`request-feed-before-names-${width}.png`)});
    names.resolve();await page.getByText('名称补齐',{exact:true}).waitFor();
    failNews=true;await page.getByRole('button',{name:'刷新',exact:true}).click();
    await page.getByText('新闻加载失败，请重试。',{exact:true}).waitFor();
    failNews=false;await page.getByRole('button',{name:'重试',exact:true}).click();
    await page.getByText('主资讯先展示 600001',{exact:true}).waitFor();

    mode='stock';const begin=reads.length;
    await page.goto('/stock-data?code=600001');
    await page.getByRole('heading',{name:'合成证券 600001',exact:true}).waitFor();
    await waitFor(()=>reads.slice(begin).some(r=>r.path==='/api/hot-concepts'),'overview sources dispatched');
    const stockReads=reads.slice(begin).map(r=>r.path);
    assert.equal(stockReads.filter(p=>p==='/api/valuation').length,1);
    for(const path of ['/api/news','/api/reports','/api/margin','/api/financials','/api/market/technical-indicators'])
      assert.ok(!stockReads.includes(path),`non-selected source ${path} must stay lazy`);
    await page.getByTestId('stock-data-tab-events').click();
    await waitFor(()=>reads.slice(begin).some(r=>r.path==='/api/reports'),'events now requested');
    await page.getByTestId('stock-data-tab-capital').click();
    await waitFor(()=>reads.slice(begin).some(r=>r.path==='/api/margin'),'capital now requested');
    await page.getByTestId('stock-data-tab-market').click();
    await waitFor(()=>reads.slice(begin).some(r=>r.path==='/api/market/technical-indicators'),'technical indicators lazy');
    assert.ok(!reads.slice(begin).some(r=>r.path==='/api/kline'),'optional panel stays on demand');
    await page.getByRole('button',{name:/历史 K 线/}).click();
    await page.getByRole('button',{name:/历史 K 线.*加载失败/}).waitFor();
    failKline=false;await page.getByTitle('重试',{exact:true}).click();
    await page.getByRole('button',{name:/历史 K 线.*暂无数据/}).waitFor();
    assert.equal(reads.slice(begin).filter(r=>r.path==='/api/kline').length,2,'explicit retry dispatches again');
    await page.screenshot({path:join(output,`request-stock-lazy-${width}.png`)});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
    assert.equal(overflow,false,`no document horizontal overflow at ${width}`);

    holdOld=true;await page.goto('/stock-data?code=600001');
    await waitFor(()=>reads.filter(r=>r.path==='/api/valuation'&&r.code==='600001').length>=2,'old primary held');
    await page.goto('/stock-data?code=600002');
    await page.getByRole('heading',{name:'合成证券 600002',exact:true}).waitFor();
    oldPrimary.resolve();await page.waitForTimeout(50);
    assert.equal(await page.getByRole('heading',{name:'合成证券 600001',exact:true}).count(),0,'unmounted old page cannot fill current stock');
    await page.screenshot({path:join(output,`request-stock-cancel-${width}.png`)});
    return {width,feed:'progressive-code-fallback/retry',stock:'lazy-tabs/late-old-result',reads};
  } finally {
    names.resolve();oldPrimary.resolve();
    await page.goto('/intel?tab=reports');
    await page.unroute('**/api/**',handler);
  }
}
