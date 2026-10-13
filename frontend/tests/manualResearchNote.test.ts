import assert from "node:assert/strict";
import test from "node:test";
import { manualResearchNotePayload, type ManualResearchNoteDraft } from "../src/lib/manualResearchNote.ts";
import { addNote, createNotesBackupJson, parseNotesBackupJson } from "../src/lib/notes.ts";

const draft = (extra: Partial<ManualResearchNoteDraft> = {}): ManualResearchNoteDraft => ({
  title: " 用户记录 ", content: " 事实与推断待核对 ", securityCode: "", sourceTitle: "", sourceUrl: "", ...extra,
});
test("ordinary manual notes need no security, AI provider or formal state", () => {
  const payload = manualResearchNotePayload(draft());
  assert.deepEqual(payload, { kind: "暂定研究", title: "用户记录", content: "用户手动记录，尚未核验。\n\n事实与推断待核对" });
  assert.equal("research" in payload, false);
});
test("manual note validation rejects blank, oversized and partial identities", () => {
  for (const fields of [{ title: " " }, { title: "x".repeat(121) }, { content: "\n" }, { content: "x".repeat(6001) }, { securityCode: "12345" }, { securityCode: "12x456" }]) {
    assert.throws(() => manualResearchNotePayload(draft(fields)));
  }
  assert.equal(manualResearchNotePayload(draft({ title: "x".repeat(120), content: "x".repeat(6000) })).title.length, 120);
});
test("optional source association uses the existing security metadata policy", () => {
  for (const sourceUrl of ["https://example.test/report", "/evidence/synthetic-1"]) {
    const payload = manualResearchNotePayload(draft({ securityCode: "000001", sourceTitle: "来源待核验", sourceUrl }));
    assert.deepEqual(payload.research, { securityCode: "000001", sourceLinks: [{ title: "来源待核验", url: sourceUrl }] });
    assert.equal("returnTo" in payload.research!, false, "do not invent a previously visited research location");
  }
  for (const sourceUrl of ["javascript:alert(1)", "data:text/html,hello", "//example.test", "https://user:secret@example.test", "/settings", "/my-reports?report=unknown"]) {
    assert.throws(() => manualResearchNotePayload(draft({ securityCode: "000001", sourceTitle: "x", sourceUrl })), /来源链接/);
  }
  assert.throws(() => manualResearchNotePayload(draft({ sourceTitle: "x", sourceUrl: "https://example.test" })), /股票代码/);
  assert.throws(() => manualResearchNotePayload(draft({ securityCode: "000001", sourceTitle: "x" })), /一起填写/);
  assert.throws(() => manualResearchNotePayload(draft({ securityCode: "000001", sourceTitle: "x".repeat(201), sourceUrl: "https://example.test" })), /最多/);
});
test("manual notes persist via the existing checked storage and backup contract", () => {
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  } });
  try {
    const payload = manualResearchNotePayload(draft({ securityCode: "000001", sourceTitle: "Source", sourceUrl: "/evidence/123" }));
    const notes = addNote(payload.kind, payload.title, payload.content, payload.research);
    assert.deepEqual(parseNotesBackupJson(createNotesBackupJson(notes)), notes);
    assert.deepEqual([...storage.keys()], ["vr-notes"]);
    storage.set("vr-notes", "corrupt-original");
    assert.throws(() => addNote(payload.kind, payload.title, payload.content, payload.research), /原始数据已保留/);
    assert.equal(storage.get("vr-notes"), "corrupt-original");
  } finally { delete (globalThis as { localStorage?: unknown }).localStorage; }
});
