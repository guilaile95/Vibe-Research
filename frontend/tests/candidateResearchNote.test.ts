import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import type { EvidenceRecord } from "../src/lib/api/types.ts";
import { candidateResearchContext, candidateResearchSelection, candidateResearchSourceLinks, parseNoteResearchMetadata, safeResearchSourceUrl } from "../src/lib/researchNote.ts";
import { addNote, createNotesBackupJson, importNotesBackupJson, loadNotesState, parseNotesBackupJson } from "../src/lib/notes.ts";

const evidence = (id: string, overrides: Partial<EvidenceRecord> = {}): EvidenceRecord => ({
  id, subject_type: "stock", subject_id: "600519", evidence_type: "financial_filing", claim: `fixture claim ${id}`,
  source_title: "合成财报摘录", source_url: "https://example.com/report", source_date: "2026-09-01", accessed_at: "2026-09-02T00:00:00Z",
  classification: "inference", confidence: "low", created_at: "2026-09-02T00:00:00Z", updated_at: "2026-09-02T00:00:00Z", deleted: 0, deleted_at: null,
  ...overrides,
});

test("candidate AI context is explicit opt-in, security scoped, bounded and preserves evidence uncertainty", () => {
  const records = [evidence("chosen"), evidence("unselected"), evidence("other", { subject_id: "000001" }), evidence("deleted", { deleted: 1 })];
  const empty = candidateResearchContext("600519", records, []);
  assert.match(empty, /没有选择证据/);
  assert.doesNotMatch(empty, /fixture claim/);
  const selected = candidateResearchContext("600519", records, records.map((record) => record.id).filter((id) => id !== "unselected"));
  assert.match(selected, /fixture claim chosen/);
  assert.match(selected, /分类：inference；置信度：low/);
  assert.match(selected, /不代表已读取原始来源全文/);
  assert.doesNotMatch(selected, /fixture claim (unselected|other|deleted)/);
  const many = Array.from({ length: 15 }, (_, index) => evidence(String(index)));
  assert.equal(candidateResearchSelection("600519", many, many.map((record) => record.id)).length, 10);
  assert.deepEqual(candidateResearchSelection("000001", records, ["chosen"]), []);
});

test("note metadata retains the same candidate return context and rejects unsafe or mismatched links", () => {
  const returnTo = `/candidates/600519?${new URLSearchParams({ source: "discovery", strategy: "SWING", return_to: "/screener?mode=discovery&strategy=SWING#discovery-item-SWING-600519" })}#candidate-research-note`;
  const metadata = { securityCode: "600519", question: "完整研究问题", sourceLinks: [{ title: "财报", url: "https://example.com/report" }], returnTo, tentativeView: "待核验", contraryEvidence: "现金流未知", nextQuestion: "下次核对现金流" };
  const parsed = parseNoteResearchMetadata(metadata);
  assert.deepEqual({ ...parsed, returnTo }, metadata);
  const parsedReturn = new URL(parsed.returnTo!, "http://localhost");
  assert.equal(parsedReturn.searchParams.get("return_to"), "/screener?mode=discovery&strategy=SWING#discovery-item-SWING-600519");
  assert.equal(parsedReturn.hash, "#candidate-research-note");
  for (const returnPath of ["//outside.example", "/candidates/000001", "/settings", "javascript:alert(1)"]) {
    assert.throws(() => parseNoteResearchMetadata({ ...metadata, returnTo: returnPath }));
  }
  for (const url of ["javascript:alert(1)", "data:text/html,hi", "https://user:secret@example.com", "//outside.example", "/settings"]) {
    assert.equal(safeResearchSourceUrl(url), null);
    assert.throws(() => parseNoteResearchMetadata({ ...metadata, sourceLinks: [{ title: "bad", url }] }));
  }
  assert.equal(safeResearchSourceUrl("/evidence/example"), "/evidence/example");
  assert.deepEqual(candidateResearchSourceLinks([evidence("no-url", { source_url: null })]), [{ title: "合成财报摘录", url: "/evidence/no-url" }]);
});

test("research note metadata survives save/reload and backup alongside legacy notes without formal writes", () => {
  const values = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key),
  } });
  try {
    const legacy = addNote("问AI", "旧记录", "旧正文")[0];
    const metadata = { securityCode: "600519", returnTo: "/candidates/600519#candidate-research-note", question: "为什么", nextQuestion: "核对财报", tentativeView: "暂定" };
    const saved = addNote("暂定研究", "600519 暂定", "未核验正文", metadata)[0];
    assert.deepEqual(loadNotesState().notes[0].research, metadata);
    assert.equal(loadNotesState().notes[1].research, undefined);
    const raw = createNotesBackupJson(loadNotesState().notes);
    assert.deepEqual(parseNotesBackupJson(raw), [saved, legacy]);
    values.set("vr-notes", "[]");
    assert.equal(importNotesBackupJson(raw).added, 2);
    assert.deepEqual(loadNotesState().notes.find((note) => note.id === saved.id)?.research, metadata);
    assert.deepEqual([...values.keys()], ["vr-notes"]);
    assert.throws(() => addNote("问AI", "invalid", "must not write", { securityCode: "invalid" }));
    assert.equal(loadNotesState().notes.length, 2);
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous); else Reflect.deleteProperty(globalThis, "localStorage");
  }
});

test("candidate journey mounts existing AI and local notes without formal-state mutation", () => {
  const component = readFileSync(new URL("../src/components/campaign/CandidateResearchNote.tsx", import.meta.url), "utf8");
  const page = readFileSync(new URL("../src/pages/CandidateWorkspace.tsx", import.meta.url), "utf8");
  assert.match(component, /useState<string\[\]>\(\[\]\)/);
  assert.match(component, /<AskAiButton context=\{context\} scopeKey=\{code\} initialQuestion=\{question\} noteMetadata=\{metadata\}/);
  assert.doesNotMatch(component, /api\.(create|update|commit|transition|evidenceCreate)/);
  assert.match(component, /未经用户确认/);
  assert.match(page, /subject_type: "stock", subject_id: code/);
  assert.match(page, /已有记录，待核验/);
  assert.doesNotMatch(page, /最高影响的下一研究问题|CheckCircle2/);
  assert.match(page, /<CandidateResearchNote\s+key=\{code\}/);
});
