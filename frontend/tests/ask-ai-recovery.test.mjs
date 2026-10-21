import test from 'node:test';
import assert from 'node:assert/strict';
import { harness, flush } from './helpers/askAiHarness.mjs';
const key = scope => `vr-askai-chat:/myreports#${scope}@runtime-a`;
const pair = (q='old question',a='old answer') => [{role:'user',content:q},{role:'assistant',content:a}];
const text = h => h.all().flatMap(n => [n.props?.children].flat(Infinity).filter(v=>typeof v === 'string')).join('\n');
async function answer(h, q, a) {
  h.type(q); const promise = h.click('发送');
  const request = h.requests.at(-1); request.args[2].onDelta(a); h.render();
  request.resolve(); await promise; await flush(); h.render();
}
test('corrupt JSON and invalid shapes survive mount, replay, scope switches and remain exportable', () => {
  for (const raw of ['{broken', '{}', '[{"role":"user","content":"orphan"}]', '[{"role":"user","content":42},{"role":"assistant","content":"a"}]']) {
    const h=harness(); h.storage.set(key('B'),raw); h.render({scopeKey:'B'}); h.open(); h.replayEffects();
    assert.equal(h.storage.get(key('B')),raw); assert.equal(h.writes.length,0);
    assert.match(text(h),/存档损坏/);
    const link=h.all().find(n=>n.props?.['aria-label']==='导出原始存档');
    assert.equal(decodeURIComponent(link.props.href.split(',')[1]),raw);
    h.render({scopeKey:'A'}); h.render({scopeKey:'B'}); assert.equal(h.storage.get(key('B')),raw);
    h.click('清空损坏存档'); assert.equal(h.storage.has(key('B')),false);
  }
});
test('read failure does not masquerade as empty or trigger writes',()=>{
 const h=harness(); h.storage.set(key('B'),'protected'); h.failures.read=true; h.render({scopeKey:'B'}); h.open();
 assert.match(text(h),/无法读取/); assert.equal(h.writes.length,0); h.click('清空损坏存档'); assert.equal(h.storage.get(key('B')),'protected');
});
test('oversized input preserves draft and previous archive without invoking model',()=>{
 const h=harness(); const raw=JSON.stringify(pair()); h.storage.set(key('B'),raw); h.render({scopeKey:'B'});h.open();h.type('x'.repeat(80001));h.click('发送');
 assert.equal(h.requests.length,0);assert.equal(h.input().length,80001);assert.equal(h.storage.get(key('B')),raw);assert.match(text(h),/未发送/);
});
test('exact budget persists; oversized response remains visible/exportable and excludes only oversized turn from context',async()=>{
 const h=harness();h.open();await answer(h,'q','a'.repeat(79999));assert.equal(JSON.parse(h.storage.get(key('A')))[1].content.length,79999);
 const raw=h.storage.get(key('A'));await answer(h,'short','z'.repeat(80001));
 assert.equal(h.storage.get(key('A')),raw);assert.match(text(h),/超长回答未写入/);
 const exported=h.all().find(n=>n.props?.['aria-label']==='导出当前对话');const msgs=JSON.parse(decodeURIComponent(exported.props.href.split(',')[1]));assert.equal(msgs.at(-1).content.length,80001);
 h.type('next'); const next=h.click('发送');assert.ok(h.requests.at(-1).args[0].every(m=>!m.content.includes('zzzz')));
 h.requests.at(-1).resolve();await next;h.render();assert.ok(h.all().some(n=>n.props?.['aria-label']==='导出当前对话'));
});
test('normal history trims complete old turns, failed writes are visible and retryable',async()=>{
 const h=harness();h.open();await answer(h,'q','a'.repeat(40000));await answer(h,'new','b'.repeat(40000));
 assert.equal(JSON.parse(h.storage.get(key('A'))).length,2);assert.equal(JSON.parse(h.storage.get(key('A')))[0].content,'new');
 h.failures.write=true;await answer(h,'third','third answer');assert.match(text(h),/quota/);assert.equal(JSON.parse(h.storage.get(key('A')))[0].content,'new');
 h.failures.write=false;h.click('重试保存对话');assert.equal(JSON.parse(h.storage.get(key('A'))).at(-1).content,'third answer');
});
test('concurrent archive changes cannot be overwritten or explicitly cleared by stale view',async()=>{
 const h=harness();h.open();await answer(h,'q','a');const replacement=JSON.stringify(pair('other','tab'));h.storage.set(key('A'),replacement);
 await answer(h,'next','next answer');assert.equal(h.storage.get(key('A')),replacement);assert.match(text(h),/其他窗口/);
 h.click('清空损坏存档');assert.equal(h.storage.get(key('A')),replacement);
});
test('clear and runtime changes reject late chunks; partial answers never enter storage',async()=>{
 const h=harness();h.open();await answer(h,'old','saved');h.type('new');const p=h.click('发送');const r=h.requests.at(-1);r.args[2].onDelta('partial');h.render();assert.equal(JSON.parse(h.storage.get(key('A'))).length,2);
 h.click('清空本页对话');r.args[2].onDelta('late');r.resolve();await p;h.render();assert.equal(h.storage.has(key('A')),false);
 h.type('runtime');const p2=h.click('发送');const r2=h.requests.at(-1);h.runtime('runtime-b');r2.args[2].onDelta('late runtime');r2.resolve();await p2;h.render();assert.equal(h.storage.has(key('A')),false);
});
test('80000-character input is accepted, but an 80001-character complete turn never replaces its archive',async()=>{
 const h=harness();h.open();await answer(h,'old','old answer');const raw=h.storage.get(key('A'));
 h.type('q'.repeat(80000));const pending=h.click('发送');assert.equal(h.requests.at(-1).args[0].at(-1).content.length,80000);
 h.requests.at(-1).args[2].onDelta('a');h.requests.at(-1).resolve();await pending;h.render();
 assert.equal(h.storage.get(key('A')),raw);assert.match(text(h),/超长回答未写入/);
 const exported=h.all().find(n=>n.props?.['aria-label']==='导出当前对话');const msgs=JSON.parse(decodeURIComponent(exported.props.href.split(',')[1]));assert.equal(msgs.at(-2).content.length+msgs.at(-1).content.length,80001);
});
test('message-count cap trims only complete oldest pairs',async()=>{
 const h=harness();h.open();for(let i=0;i<21;i++)await answer(h,`q${i}`,`a${i}`);
 const stored=JSON.parse(h.storage.get(key('A')));assert.equal(stored.length,40);assert.equal(stored[0].content,'q1');assert.equal(stored.at(-1).content,'a20');
});
