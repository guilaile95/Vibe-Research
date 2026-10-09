// Static UI wiring guardrails; behavioral interaction is covered separately by
// tests/e2e/evidence-edit-conflict.browser.mjs, not claimed by these source checks.
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
const page = readFileSync(new URL("../src/pages/EvidenceDetail.tsx", import.meta.url), "utf8");
const section = (start, end) => page.slice(page.indexOf(start), page.indexOf(end, page.indexOf(start)));

test("edit token is captured on edit, never rebased by latest comparison", () => {
  assert.match(section("const startEdit", "const set ="), /setEditToken\(record\.edit_token\)/);
  assert.match(section("const save =", "const remove ="), /expected_edit_token: editToken/);
  const latest = section("const fetchLatest", "const discardAndReload");
  assert.doesNotMatch(latest, /setForm|setRecord|setEditToken|evidenceUpdate|evidenceDelete/);
  assert.match(latest, /rid !== runIdRef.current/);
});

test("409 and deleted 404 preserve edit draft and require explicit discard confirmation", () => {
  const save = section("const save =", "const remove =");
  assert.match(save, /e.status === 409 \|\| e.status === 404/);
  const failure = save.slice(save.indexOf("catch (e)"));
  assert.doesNotMatch(failure, /setForm|setEditToken|setEditing\(false\)/);
  assert.match(failure, /setConflict\(true\)/);
  const discard = section("const discardAndReload", "const startEdit");
  assert.match(discard, /if \(!confirm\(/);
  assert.ok(discard.indexOf("confirm(") < discard.indexOf("setForm({})"));
});

test("all editable fields have a visible latest-versus-draft comparison", () => {
  const comparison = section('data-testid="evidence-conflict-comparison"', 'data-testid="evidence-refresh-latest"');
  for (const key of ["evidence_type", "claim", "source_title", "source_url", "source_date", "accessed_at", "classification", "confidence"]) assert.ok(comparison.includes(`"${key}"`), key);
  assert.match(comparison, /form\[key\]/);
  assert.match(comparison, /latest\[key\]/);
});

test("write handlers reject conflict/deletion and late route responses", () => {
  for (const [start, end] of [["const save =", "const remove ="], ["const remove =", "if (loading"]]) {
    const handler = section(start, end);
    assert.match(handler, /busy \|\| conflict \|\| record.deleted/);
    assert.match(handler, /rid !== runIdRef.current/);
  }
  assert.match(page, /return \(\) => \{ \+\+runIdRef.current; \}/);
  assert.match(page, /evidenceDelete\(id, record.edit_token\)/);
});
