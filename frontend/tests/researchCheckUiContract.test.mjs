import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { researchSelectionHref } from '../src/lib/researchResume.ts';
import { assertStockEvidenceWrites } from './e2e/stock-evidence-return.fixture.mjs';
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const panel = read('../src/components/campaign/ResearchCheckPanel.tsx');
const candidate = read('../src/pages/CandidateWorkspace.tsx');
const note = read('../src/components/campaign/CandidateResearchNote.tsx');
const browser = read('./e2e/research-check-loop.browser.mjs');
const discovery = read('../src/components/discovery/DiscoveryWorkspace.tsx');
test('candidate has a bounded material-check entry alongside existing workflow and one combined SPA blocker', () => {
  assert.match(candidate, /<ResearchCheckPanel/); assert.match(candidate, /onDirtyChange=\{setCheckDirty\}/); assert.match(candidate, /onDirtyChange=\{setNoteDirty\}/);
  assert.match(candidate, /to=\{\{ pathname: location\.pathname, search: location\.search, hash: `#\$\{id\}` \}\}\s+state=\{location\.state\}/);
  assert.equal((candidate.match(/useBlocker\(/g) || []).length, 1); assert.doesNotMatch(note + panel, /useBlocker|<dialog|role="alertdialog"|beforeunload/); assert.match(candidate, /researchNavigationRisk/);
});
test('check panel never invokes a model, changes formal state, fetches arbitrary URL or auto-migrates notes', () => {
  assert.doesNotMatch(panel, /AskAiButton|chatStream|api\.(?:create|evidenceCreate|patchReport|uploadReport|indexMyReport|chat|commit|transition)/);
  assert.match(panel, /api\.readReportPages/); assert.match(panel, /api\.searchMyReportText/);
  assert.match(panel, /initialRound: round/); assert.match(panel, /expectedRevision: active\.revision/); assert.match(panel, /expectedHeadRoundId: active\.headRoundId/);
  assert.match(panel, /<fieldset disabled=\{busy \|\| loading \|\| navigationPending \|\| resumeState !== "ready"\}/); assert.match(panel, /草稿未清空/); assert.match(panel, /if \(busy \|\| navigationPending \|\| resumeState !== "ready" \|\| reading \|\| searching\) return/); assert.match(panel, /generation !== requestGeneration\.current/); assert.match(panel, /先前提交的研究轮次已保存/);
  assert.match(panel, /listLegacyNotes/); assert.match(panel, /checkLegacySource/); assert.match(panel, /确认复制/); assert.match(panel, /coverage: "partial"/);
  assert.match(panel, /file\.size > RESEARCH_DEFAULT_BUDGET_BYTES \* 4/);
});
test('one production-dist browser fixture owns full T0→reopen→T1→original sequence, failure and manual stage semantics', () => {
  for (const token of ['hit-page-cancels-stale-read', 'held-save-discard-race', 'minimal-next-question-only', 'T0-first-question', 'close-reopen-T0', 'SPA-draft-retention', 'T1-availability-and-delayed-read', 'alignment-fail-closed', 'failed-save-retains-draft', 'two-page-conflict', 'manual-stage-history-counterexample', 'layout-and-no-side-effects']) assert.ok(browser.includes(token), token);
  assert.match(browser, /page\.close\(\); page = await context\.newPage/);
  assert.match(browser, /assert\.deepEqual\(T1\.rounds\.find\(round => round\.id === t0\.id\), t0/);
  assert.match(browser, /assertStockEvidenceWrites\(writes\)/);
  assert.match(browser, /for \(const width of \[1440, 390, 320\]\)/);
});

test('discovery card passes validated bounded snapshot separately from optional human reason', () => {
  assert.match(discovery, /state=\{\{ discoveryResearchOrigin: buildDiscoveryResearchOrigin\(item, snapshot, gaps\) \}\}/);
  assert.match(candidate, /parseDiscoveryResearchOrigin/); assert.match(candidate, /parsedDiscoveryOrigin\?\.strategy === discoveryStrategy/);
  assert.match(panel, /snapshot: discoveryOrigin/); assert.match(panel, /check-discovery-origin/); assert.match(panel, /未记录 \/ 待核/);
  assert.doesNotMatch(panel, /!why\.trim\(\)|!limitations\.trim\(\)/);
  assert.match(browser, /page\.goto\('\/screener\?mode=discovery&strategy=SWING'\)/);
  assert.match(browser, /getByTestId\('discovery-candidate-600519'\)\.click/);
  assert.match(browser, /q\.origin\.snapshot\.observations/);
});


test('history lookup preserves CAS while explicit reconcile alone updates current draft head', () => {
  assert.match(panel, /store\.getQuestionContext/);
  assert.match(panel, /if \(\(activeRef\.current\?\.id \|\| null\) !== question\.id\) \{ setActive\(question\); clearDraft\(question\); \}/);
  assert.match(panel, /generation !== requestGeneration\.current \|\| hrefRef\.current\.split\("#"\)\[0\] !== expectedHref\.split\("#"\)\[0\]/);
  assert.match(panel, /finally \{ if \(mounted\.current && generation === requestGeneration\.current\) setBusy\(false\); \}/);
  assert.match(candidate, /expectedHref !== undefined && expectedHref\.split\("#"\)\[0\] !== from\.split\("#"\)\[0\]/);
  assert.doesNotMatch(candidate, /history\.replaceState/);
});

// Execute the actual callback bodies with a committed browser history location
// and deliberately stale rendered location, as React Router transitions permit.
const callbackBody = (name, end) => candidate.split(`const ${name} = useCallback(`)[1].split('=> {')[1].split(end)[0];
test('late selection receipt preserves the live hash before router render catches up', () => {
  const rendered = '/candidates/600519?question=Q2#candidate-research-check';
  const window = { location: new URL(rendered, 'https://synthetic.test') };
  const syncReceipt = { current: null }, calls = [], errors = [];
  const navigate = (to, options) => calls.push({ to, options, receipt: syncReceipt.current });
  const change = new Function('window', 'currentHrefRef', 'researchSelectionHref', 'setSelectionError', 'syncReceipt', 'navigate', 'location',
    `return (questionId, roundId, replace = false, expectedHref) => {${callbackBody('changeSelection', '\n  }, [navigate, location.state]);')}};`)
    (window, { current: rendered }, researchSelectionHref, value => errors.push(value), syncReceipt, navigate, { state: null });
  window.location = new URL('/candidates/600519?question=Q2#candidate-research-note', window.location);
  change('Q2', 'R3', true, rendered);
  assert.deepEqual(calls, [{ to: '/candidates/600519?question=Q2&round=R3#candidate-research-note', options: { replace: true, state: null }, receipt: { from: '/candidates/600519?question=Q2#candidate-research-note', to: '/candidates/600519?question=Q2&round=R3#candidate-research-note' } }]);
  assert.equal(syncReceipt.current, null);
  for (const href of ['/candidates/600519?question=Q3#candidate-research-note', '/candidates/000001?question=Q2#candidate-research-note', '/candidates/600519?question=Q2&round=R1#candidate-research-note']) {
    window.location = new URL(href, window.location);
    change('Q2', 'R3', true, rendered);
    assert.equal(calls.length, 1, href);
    assert.deepEqual(errors, [''], href);
  }
});

test('late validated visit records the live hash but never a different live locator', () => {
  const rendered = '/candidates/600519?question=Q2&round=R3#candidate-research-check';
  const window = { location: new URL(rendered, 'https://synthetic.test') };
  const validatedLocation = { current: null }, visits = [];
  const visit = new Function('window', 'currentHrefRef', 'validatedLocation', 'rememberResearchVisit',
    `return href => {${callbackBody('validatedVisit', '\n  }, []);')}};`)
    (window, { current: rendered }, validatedLocation, href => visits.push(href));
  window.location = new URL('/candidates/600519?question=Q2&round=R3#candidate-research-note', window.location);
  visit(rendered);
  assert.deepEqual(visits, ['/candidates/600519?question=Q2&round=R3#candidate-research-note']);
  assert.equal(validatedLocation.current, '/candidates/600519?question=Q2&round=R3');
  for (const href of ['/candidates/600519?question=Q3&round=R3', '/candidates/000001?question=Q2&round=R3', '/candidates/600519?question=Q2&round=R1']) {
    window.location = new URL(href, window.location);
    visit(rendered);
    assert.equal(visits.length, 1, href);
  }
});


test('capture write audit permits one POST in each explicit save phase and rejects navigation or extra writes', () => {
  const saves = ['announcement', 'news'].map(type => ({ phase: `stock-evidence-explicit-save-${type}`, method: 'POST', path: '/api/evidence', savingType: type, body: { evidence_type: type } }));
  assert.doesNotThrow(() => assertStockEvidenceWrites(saves));
  for (const phase of ['stock-evidence-return-chain', 'resume-deep-link-history-and-tools', 'stock-evidence-explicit-save-news']) {
    assert.throws(() => assertStockEvidenceWrites([{ ...saves[0], phase }, saves[1]]));
  }
  assert.throws(() => assertStockEvidenceWrites([...saves, saves[0]]));
  assert.throws(() => assertStockEvidenceWrites(saves.slice(1)));
  for (const mutation of [{ path: '/api/thesis' }, { method: 'PUT' }, { savingType: 'news' }, { body: { evidence_type: 'news' } }]) {
    assert.throws(() => assertStockEvidenceWrites([{ ...saves[0], ...mutation }, saves[1]]));
  }
});
