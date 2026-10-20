import assert from 'node:assert/strict';
import test from 'node:test';
import { applyReviewResponse, reviewRequest } from '../src/lib/eventResearchReview.ts';

test('late review/context responses cannot replace a changed selection or unmounted UI', () => {
  assert.equal(applyReviewResponse(1, 2, true), false);
  assert.equal(applyReviewResponse(2, 2, false), false);
  assert.equal(applyReviewResponse(2, 2, true), true);
});

test('review request uses explicit POST and surfaces optimistic conflict without retry', async () => {
  const calls: Array<{url:string; init?:RequestInit}> = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({url,init});
    return new Response(JSON.stringify({detail:'证据已更新，请重新审阅'}), {status:409});
  }) as typeof fetch;
  await assert.rejects(reviewRequest('/review-id/judgment', {expected_version:1}), /证据已更新/);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/research-events/reviews/review-id/judgment');
  assert.equal(calls[0].init?.method,'POST');
  assert.equal(calls[0].init?.body, JSON.stringify({expected_version:1}));
});
