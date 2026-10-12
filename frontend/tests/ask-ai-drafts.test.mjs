import assert from 'node:assert/strict';
import test from 'node:test';
import { harness, flush, componentModule } from './helpers/askAiHarness.mjs';

test('mounted scope A → B → A restores exact unsent text without requests or draft storage', () => {
  const h = harness(); h.open(); h.type('  synthetic A\n'); h.render({ scopeKey: 'B' });
  assert.equal(h.input(), ''); h.type('synthetic B'); h.render({ scopeKey: 'A' });
  assert.equal(h.input(), '  synthetic A\n'); h.render({ scopeKey: 'B' });
  assert.equal(h.input(), 'synthetic B'); assert.equal(h.requests.length, 0);
  assert.ok(h.writes.every(([, value]) => value === null));
});

test('full route, scope, report, version, range and runtime identities isolate mounted drafts', () => {
  const page = { report_id: 'report-a', expected_file_sha256: 'a'.repeat(64), page_from: 1, page_to: 2 };
  const h = harness({ reportPageContext: page }); h.open(); h.type('original');
  const variants = [
    { report_id: 'report-b' }, { expected_file_sha256: 'b'.repeat(64) }, { page_from: 2 }, { page_to: 3 },
  ];
  variants.forEach((change, i) => {
    h.render({ reportPageContext: { ...page, ...change } }); assert.equal(h.input(), ''); h.type(`variant-${i}`);
  });
  h.render({ reportPageContext: page }); assert.equal(h.input(), 'original');
  variants.forEach((change, i) => {
    h.render({ reportPageContext: { ...page, ...change } }); assert.equal(h.input(), `variant-${i}`);
  });
  h.render({ reportPageContext: page }); h.route('/other'); assert.equal(h.input(), ''); h.type('route');
  h.route('/myreports'); assert.equal(h.input(), 'original');
  h.runtime('runtime-b'); assert.equal(h.input(), ''); h.type('runtime');
  h.runtime('runtime-a'); assert.equal(h.input(), 'original');
  h.runtime('runtime-b'); assert.equal(h.input(), 'runtime');
  assert.equal(h.requests.length, 0);
});

test('identical keys in simultaneous instances do not share drafts; remount discards them', () => {
  const module = componentModule();
  const a = harness({}, module), b = harness({}, module); a.open(); b.open(); a.type('private to A');
  assert.equal(b.input(), ''); b.type('private to B'); assert.equal(a.input(), 'private to A');
  a.unmount(); const remounted = harness({}, module); remounted.open(); assert.equal(remounted.input(), '');
  assert.equal(b.input(), 'private to B'); assert.equal(remounted.requests.length, 0);
});

test('send clears only its key and sends trimmed question through unchanged request identity', async () => {
  const h = harness(); h.open(); h.type('  question A  '); h.render({ scopeKey: 'B' }); h.type('draft B');
  h.render({ scopeKey: 'A' }); const sent = h.click('发送');
  assert.equal(h.input(), ''); assert.equal(h.requests.length, 1);
  const request = h.requests[0];
  assert.equal(request.args[0][0].content, 'question A');
  assert.equal(request.args[4], 'vr-askai-chat:/myreports#A@runtime-a:0');
  h.render({ scopeKey: 'B' }); assert.equal(h.input(), 'draft B'); assert.equal(request.args[3].aborted, true);
  request.args[2].onDelta('late answer'); request.resolve(); await sent; h.render();
  assert.equal(h.input(), 'draft B'); h.render({ scopeKey: 'A' }); assert.equal(h.input(), '');
  assert.ok(h.writes.every(([, value]) => !value?.includes('draft B')));
});

test('pre-send validation restores trimmed input without a request and without touching other keys', () => {
  const h = harness({ noteMetadata: { invalid: true } }); h.open(); h.type('  invalid question  ');
  h.render({ scopeKey: 'B' }); h.type('B'); h.render({ scopeKey: 'A' }); h.click('发送');
  assert.equal(h.input(), 'invalid question'); assert.equal(h.requests.length, 0);
  h.render({ scopeKey: 'B' }); assert.equal(h.input(), 'B');
});

test('clear history preserves unsent input; close/reopen and effect replay preserve it too', async () => {
  const h = harness(); h.open(); h.type('question'); const sent = h.click('发送');
  h.requests[0].args[2].onDelta('answer'); h.requests[0].resolve(); await sent; h.render();
  h.type('unsent draft'); h.click('清空本页对话'); assert.equal(h.input(), 'unsent draft');
  h.click('关闭'); h.open(); assert.equal(h.input(), 'unsent draft');
  h.replayEffects(); assert.equal(h.input(), 'unsent draft');
  h.render({ scopeKey: 'B' }); h.render({ scopeKey: 'A' }); assert.equal(h.input(), 'unsent draft');
  assert.equal(h.requests.length, 1);
  assert.ok(h.writes.some(([key, value]) => key.startsWith('vr-askai-epoch:') && value === '1'));
  assert.ok(h.writes.every(([, value]) => !value?.includes('unsent draft')));
});

test('late rejected stream after navigation does not erase either new draft', async () => {
  const h = harness(); h.open(); h.type('send'); const sent = h.click('发送');
  h.type('new A'); h.render({ scopeKey: 'B' }); h.type('new B');
  h.requests[0].reject(new Error('synthetic failure')); await sent; await flush(); h.render();
  assert.equal(h.input(), 'new B'); h.render({ scopeKey: 'A' }); assert.equal(h.input(), 'new A');
});

test('unmount aborts stream; late callbacks cannot populate a fresh instance', async () => {
  const h = harness(); h.open(); h.type('send'); const sent = h.click('发送'); h.type('discard me'); h.unmount();
  assert.equal(h.requests[0].args[3].aborted, true);
  const next = harness(); next.open(); next.type('new instance');
  h.requests[0].args[2].onDelta('late'); h.requests[0].resolve(); await sent;
  assert.equal(next.input(), 'new instance'); assert.equal(next.requests.length, 0);
});

test('explicit initial question retains existing replacement behavior, with no automatic send', () => {
  const h = harness({ initialQuestion: 'prefilled question' }); h.open(); assert.equal(h.input(), 'prefilled question');
  h.type('edited'); h.click('关闭'); h.open(); assert.equal(h.input(), 'prefilled question');
  assert.equal(h.requests.length, 0);
});

test('empty and loading sends keep input and do not start extra requests', async () => {
  const h = harness(); h.open(); h.type('   '); h.click('发送'); assert.equal(h.input(), '   ');
  h.type('question'); const sent = h.click('发送'); h.type('next draft');
  const textarea = h.all().find(node => node.type === 'textarea');
  textarea.props.onKeyDown({ key: 'Enter', shiftKey: false, preventDefault() {} }); h.render();
  assert.equal(h.input(), 'next draft'); assert.equal(h.requests.length, 1);
  h.requests[0].resolve(); await sent;
});
