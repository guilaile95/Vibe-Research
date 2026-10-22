import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const panel = read('../src/components/campaign/ResearchCheckPanel.tsx');
const candidate = read('../src/pages/CandidateWorkspace.tsx');
const note = read('../src/components/campaign/CandidateResearchNote.tsx');
const browser = read('./e2e/research-check-loop.browser.mjs');
test('candidate has a bounded material-check entry alongside existing workflow and one combined SPA blocker', () => {
  assert.match(candidate, /<ResearchCheckPanel/); assert.match(candidate, /onDirtyChange=\{setCheckDirty\}/); assert.match(candidate, /additionalDirty=\{checkDirty\}/);
  assert.match(note, /const dirty = ownDirty \|\| additionalDirty/); assert.match(note, /useBlocker/); assert.doesNotMatch(panel, /useBlocker/);
});
test('check panel never invokes a model, changes formal state, fetches arbitrary URL or auto-migrates notes', () => {
  assert.doesNotMatch(panel, /AskAiButton|chatStream|api\.(?:create|evidenceCreate|patchReport|uploadReport|indexMyReport|chat|commit|transition)/);
  assert.match(panel, /api\.readReportPages/); assert.match(panel, /api\.searchMyReportText/);
  assert.match(panel, /initialRound: round/); assert.match(panel, /expectedRevision: active\.revision/); assert.match(panel, /expectedHeadRoundId: active\.headRoundId/);
  assert.match(panel, /<fieldset disabled=\{busy\}/); assert.match(panel, /草稿未清空/);
  assert.match(panel, /listLegacyNotes/); assert.match(panel, /checkLegacySource/); assert.match(panel, /确认复制/); assert.match(panel, /coverage: "partial"/);
  assert.match(panel, /file\.size > RESEARCH_DEFAULT_BUDGET_BYTES \* 4/);
});
test('one production-dist browser fixture owns full T0→reopen→T1→original sequence, failure and manual stage semantics', () => {
  for (const token of ['T0-first-question', 'close-reopen-T0', 'SPA-draft-retention', 'T1-availability-and-delayed-read', 'alignment-fail-closed', 'failed-save-retains-draft', 'two-page-conflict', 'manual-stage-history-counterexample', 'layout-and-no-side-effects']) assert.ok(browser.includes(token), token);
  assert.match(browser, /page\.close\(\); page = await context\.newPage/);
  assert.match(browser, /assert\.deepEqual\(T1\.rounds\.find\(round => round\.id === t0\.id\), t0/);
  assert.match(browser, /assert\.deepEqual\(writes, \[\]/);
  assert.match(browser, /for \(const width of \[1440, 390\]\)/);
});
