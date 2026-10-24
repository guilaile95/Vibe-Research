import "./helpers/notes-locks.ts";
import assert from "node:assert/strict";
import test from "node:test";
import { addNote, createNotesBackupJson, parseNotesBackupJson, importNotesBackupJson, loadNotesState, deleteNote, NOTES_LIMIT } from "../src/lib/notes.ts";
import { dailyReviewNoteGeneration, parseNoteGeneration } from "../src/lib/noteGeneration.ts";
const result = {
  result_type: "daily_review_ai" as const, trade_date: "2026-10-21", schema_version: "daily_review_ai.v2",
  generated_at: "2026-10-21T08:00:00Z", model_provider: "synthetic", model_name: "fixture", stale: true,
  payload: { markdown: "正文不变\n\n# 合成结果", source_review_generated_at: "2026-10-21T07:00:00Z", source_data_cutoff: null,
    input_basis: { schema_version: "daily-review-input-basis.v1" as const, context_schema_version: "daily-review-ai-context-v0.1" as const,
      review_schema_version: "review.v1", trade_date: "2026-10-21", source_review_generated_at: "2026-10-21T07:00:00Z", source_data_cutoff: null,
      review_status: "partial" as const, component_statuses: Object.fromEntries(["indices", "global_indices", "breadth", "emotion", "turnover", "industry_boards", "concept_boards", "region_boards"].map(k => [k, "unknown" as const])),
      omitted_component_count: 1, warning_count: 2, unknown_count: 8, context_sha256: "a".repeat(64) } },
};
const generation = dailyReviewNoteGeneration(result, result.payload.markdown)!;
const storage = new Map<string,string>();
const working = { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string,v: string) => {storage.set(k,v);}, removeItem: (k: string) => {storage.delete(k);} };
test.beforeEach(() => {storage.clear(); Object.defineProperty(globalThis,"localStorage",{value:working,configurable:true});});
test.afterEach(() => {delete (globalThis as { localStorage?: unknown }).localStorage;});
const old = { id:"old",kind:"问AI",title:"旧笔记",content:"原文",ts:1,research:{securityCode:"600000"} };

test("save/reopen/export/clean import keeps original body, identity, basis and research without filling old history", async () => {
  storage.set("vr-notes",JSON.stringify([old]));
  const saved = (await addNote("复盘","合成",result.payload.markdown,undefined,generation));
  assert.equal(saved[0].research,undefined); assert.notEqual(saved[0].ts,Date.parse(generation.generatedAt));
  assert.deepEqual(loadNotesState().notes,saved);
  const raw = createNotesBackupJson(saved); assert.equal(JSON.parse(raw).schema_version,"vibe-notes.backup.v2");
  storage.clear(); (await importNotesBackupJson(raw));
  assert.deepEqual(loadNotesState().notes,saved); assert.equal(saved[0].content,result.payload.markdown);
  assert.equal(saved[1].generation,undefined); assert.deepEqual(saved[1],old);
  const later = dailyReviewNoteGeneration({...result,generated_at:"2026-10-21T09:00:00Z"}, result.payload.markdown)!;
  assert.notEqual(later.generatedAt,generation.generatedAt);
});
test("old v1 roundtrips; generation v2 rejects downgrades, duplicates and unknown versions", () => {
  assert.deepEqual(parseNotesBackupJson(createNotesBackupJson([old])),[old]);
  const raw = JSON.parse(createNotesBackupJson([{...old,generation}]));
  raw.schema_version="vibe-notes.backup.v1"; assert.throws(()=>parseNotesBackupJson(JSON.stringify(raw)),/v2/);
  raw.schema_version="vibe-notes.backup.v2"; raw.notes.push(raw.notes[0]); assert.throws(()=>parseNotesBackupJson(JSON.stringify(raw)),/重复/);
  assert.throws(()=>parseNoteGeneration({...generation,schemaVersion:"future"}),/版本/);
  assert.throws(()=>parseNoteGeneration({...generation,headers:{secret:"never store"}}),/格式/);
  assert.throws(()=>parseNoteGeneration({...generation,modelName:"x".repeat(9000)}),/格式/);
  assert.throws(()=>parseNoteGeneration({...generation,generatedAt:"2026-02-30T08:00:00Z"}),/格式/);
  assert.throws(()=>parseNoteGeneration({...generation,inputBasis:{...generation.inputBasis,trade_date:"2026-10-20"}}),/格式/);
});
test("corrupt generation blocks read-modify-write without erasing valid old records or original bytes", async () => {
  const raw = JSON.stringify([old,{...old,id:"broken",generation:{...generation,modelName:42}}]); storage.set("vr-notes",raw);
  assert.equal(loadNotesState().corruptedRaw,raw); assert.match(loadNotesState().error,/生成依据/);
  (await assert.rejects(async ()=>(await addNote("复盘","a","b",undefined,generation)))); (await assert.rejects(async ()=>(await deleteNote("old"))));
  (await assert.rejects(async ()=>(await importNotesBackupJson(createNotesBackupJson([old]))))); assert.equal(storage.get("vr-notes"),raw);
});
test("quota and limit preserve all bytes; full import skips instead of evicting; duplicates retain original", async () => {
  const notes=Array.from({length:NOTES_LIMIT},(_,i)=>({...old,id:String(i),generation}));
  const raw=JSON.stringify(notes);storage.set("vr-notes",raw);
  (await assert.rejects(async ()=>(await addNote("复盘","a","b",undefined,generation)),/上限/));assert.equal(storage.get("vr-notes"),raw);
  const merged=(await importNotesBackupJson(createNotesBackupJson([{...old,generation}])));assert.equal(merged.added,0);assert.equal(merged.skipped,1);assert.deepEqual(merged.notes.length,200);
  assert.throws(()=>createNotesBackupJson([...notes,old]),/超过/);
  storage.set("vr-notes",JSON.stringify([old]));const before=storage.get("vr-notes");
  Object.defineProperty(globalThis,"localStorage",{value:{...working,setItem:()=>{throw new Error("quota");}},configurable:true});
  (await assert.rejects(async ()=>(await addNote("复盘","a","b",undefined,generation))));assert.equal(storage.get("vr-notes"),before);
  (await assert.rejects(async ()=>(await importNotesBackupJson(createNotesBackupJson([{...old,id:"new",generation}])))));assert.equal(storage.get("vr-notes"),before);
});

test("mismatched streamed or replacement body is never assigned saved-result provenance",()=>{
 assert.equal(dailyReviewNoteGeneration(result,"different streamed result"),undefined);
 assert.equal(dailyReviewNoteGeneration({...result,result_type:"other" as typeof result.result_type},result.payload.markdown),undefined);
 assert.equal(dailyReviewNoteGeneration({...result,payload:{...result.payload,markdown:""}},result.payload.markdown),undefined);
});

test("restored matching result retains original time and duplicate-ID import cannot replace its basis",async ()=>{
 const restored=JSON.parse(JSON.stringify(result));
 assert.deepEqual(dailyReviewNoteGeneration(restored,restored.payload.markdown),generation);
 storage.set("vr-notes",JSON.stringify([{...old,generation}]));
 const changed={...generation,modelName:"replacement"};
 const merged=(await importNotesBackupJson(createNotesBackupJson([{...old,generation:changed}])));
 assert.equal(merged.added,0);assert.deepEqual(merged.notes[0].generation,generation);
});
