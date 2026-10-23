import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
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
  assert.match(browser, /assert\.deepEqual\(writes, \[\]/);
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
  assert.match(panel, /generation !== requestGeneration\.current \|\| hrefRef\.current !== expectedHref/);
  assert.match(panel, /finally \{ if \(mounted\.current && generation === requestGeneration\.current\) setBusy\(false\); \}/);
  assert.match(candidate, /expectedHref !== undefined && expectedHref !== from/);
  assert.doesNotMatch(candidate, /history\.replaceState/);
});
