import assert from "node:assert/strict";
import test from "node:test";

import {
  NOTES_BACKUP_SCHEMA_VERSION,
  NOTES_LIMIT,
  createNotesBackupJson,
  importNotesBackupJson,
  loadNotesState,
  mergeNotesFromBackup,
  parseNotesBackupJson,
  replaceCorruptedNotesFromBackupJson,
  type Note,
} from "../src/lib/notes.ts";

const storage = new Map<string, string>();
const workingStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value); },
  removeItem: (key: string) => { storage.delete(key); },
};
test.beforeEach(() => {
  storage.clear();
  Object.defineProperty(globalThis, "localStorage", { value: workingStorage, configurable: true });
});
test.afterEach(() => {
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

function note(id: string, ts: number, content = id): Note {
  return {
    id,
    kind: "今日要点",
    title: `记录 ${id}`,
    content,
    ts,
  };
}

test("research notes backup round-trips without adding secrets or unrelated browser state", () => {
  const exportedAt = "2026-09-03T09:30:00.000Z";
  const raw = createNotesBackupJson([note("n-1", 100, "长期研究结论")], exportedAt);
  const payload = JSON.parse(raw) as Record<string, unknown>;

  assert.equal(payload.schema_version, NOTES_BACKUP_SCHEMA_VERSION);
  assert.equal(payload.exported_at, exportedAt);
  assert.equal(Object.hasOwn(payload, "vr-llm"), false);
  assert.equal(Object.hasOwn(payload, "vr-access-key"), false);
  assert.equal(Object.hasOwn(payload, "vr-askai-chat"), false);
  assert.deepEqual(parseNotesBackupJson(raw), [note("n-1", 100, "长期研究结论")]);
});

test("notes backup parser fails closed on unsupported, malformed, or duplicate records", () => {
  assert.throws(() => parseNotesBackupJson("not-json"), /不是有效的 JSON/);
  assert.throws(
    () => parseNotesBackupJson(JSON.stringify({
      schema_version: "future-format",
      exported_at: "2026-09-03T09:30:00.000Z",
      notes: [],
    })),
    /不是受支持的 Vibe 研究记录备份/,
  );
  assert.throws(
    () => parseNotesBackupJson(JSON.stringify({
      schema_version: NOTES_BACKUP_SCHEMA_VERSION,
      exported_at: "2026-09-03T09:30:00.000Z",
      notes: [note("same", 2), note("same", 1)],
    })),
    /包含重复记录/,
  );
  assert.throws(
    () => parseNotesBackupJson(JSON.stringify({
      schema_version: NOTES_BACKUP_SCHEMA_VERSION,
      exported_at: "2026-09-03T09:30:00.000Z",
      notes: [{ id: "bad", kind: "复盘", title: "缺少正文", ts: 1 }],
    })),
    /content 无效/,
  );
});

test("notes import merges by id, preserves existing records, and enforces the 200-note limit", () => {
  const existing = [note("existing", 10_000, "保留当前浏览器内容")];
  const imported = [
    note("existing", 20_000, "不得覆盖"),
    ...Array.from({ length: NOTES_LIMIT }, (_, index) => note(`import-${index}`, index)),
  ];

  const result = mergeNotesFromBackup(existing, imported);

  assert.equal(result.notes.length, NOTES_LIMIT);
  assert.equal(result.notes.find((item) => item.id === "existing")?.content, "保留当前浏览器内容");
  assert.equal(result.added, NOTES_LIMIT - 1);
  assert.equal(result.skipped, 2);
  assert.equal(result.notes.some((item) => item.id === "import-0"), false);
  assert.equal(result.notes.some((item) => item.id === `import-${NOTES_LIMIT - 1}`), true);
});

test("corrupted notes expose exact raw data without treating read denial as corruption", () => {
  for (const raw of ["", " \n{broken 中文", "{}", "[null]", JSON.stringify([note("same", 1), note("same", 2)])]) {
    storage.set("vr-notes", raw);
    const state = loadNotesState();
    assert.deepEqual(state.notes, []);
    assert.notEqual(state.error, "");
    assert.equal(state.corruptedRaw, raw);
    assert.equal(storage.get("vr-notes"), raw);
  }
  Object.defineProperty(globalThis, "localStorage", {
    value: { ...workingStorage, getItem() { throw new Error("denied"); } }, configurable: true,
  });
  assert.match(loadNotesState().error, /无法读取/);
  assert.equal(loadNotesState().corruptedRaw, null);
});

test("validated recovery replaces only corrupted notes and returns to a healthy state", () => {
  const raw = " \n{broken 中文";
  storage.set("vr-notes", raw);
  storage.set("vr-llm", "SYNTHETIC_CONFIG");
  storage.set("vr-access-key", "SYNTHETIC_KEY");
  storage.set("vr-askai-chat:test", "SYNTHETIC_CHAT");
  const restored = [note("restored", 100)];
  const backup = createNotesBackupJson(restored);

  assert.throws(() => importNotesBackupJson(backup), /格式无效/);
  assert.equal(storage.get("vr-notes"), raw, "ordinary import must never silently replace corruption");
  assert.deepEqual(replaceCorruptedNotesFromBackupJson(backup, raw), restored);
  assert.deepEqual(loadNotesState(), { notes: restored, error: "", corruptedRaw: null });
  assert.equal(storage.get("vr-llm"), "SYNTHETIC_CONFIG");
  assert.equal(storage.get("vr-access-key"), "SYNTHETIC_KEY");
  assert.equal(storage.get("vr-askai-chat:test"), "SYNTHETIC_CHAT");

  const result = importNotesBackupJson(createNotesBackupJson([
    note("restored", 200, "must not overwrite"), note("added", 300),
  ]));
  assert.equal(result.added, 1);
  assert.equal(result.skipped, 1);
  assert.equal(result.notes.find((item) => item.id === "restored")?.content, "restored");
  assert.deepEqual(loadNotesState().notes, result.notes);
});

test("invalid, duplicate, or oversized recovery backups preserve the original bytes", () => {
  const raw = " \n{broken 中文";
  storage.set("vr-notes", raw);
  const valid = JSON.parse(createNotesBackupJson([note("restore", 10)]));
  const invalidBackups = [
    "not-json",
    JSON.stringify({ ...valid, schema_version: "unsupported" }),
    JSON.stringify({ ...valid, notes: [null] }),
    JSON.stringify({ ...valid, notes: [note("same", 1), note("same", 2)] }),
    JSON.stringify({ ...valid, notes: Array.from({ length: NOTES_LIMIT + 1 }, (_, i) => note(`${i}`, i)) }),
  ];
  for (const backup of invalidBackups) {
    assert.throws(() => replaceCorruptedNotesFromBackupJson(backup, raw));
    assert.equal(storage.get("vr-notes"), raw);
  }
});

test("quota failure preserves corrupted data for a successful retry without remove-first writes", () => {
  const raw = " \n{broken 中文";
  storage.set("vr-notes", raw);
  const backup = createNotesBackupJson([note("restore", 10)]);
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      ...workingStorage,
      setItem() { throw new DOMException("full", "QuotaExceededError"); },
      removeItem() { assert.fail("recovery must never remove the original before writing"); },
    }, configurable: true,
  });
  assert.throws(() => replaceCorruptedNotesFromBackupJson(backup, raw), /无法保存/);
  assert.equal(storage.get("vr-notes"), raw);
  assert.equal(loadNotesState().corruptedRaw, raw);
  Object.defineProperty(globalThis, "localStorage", { value: workingStorage, configurable: true });
  replaceCorruptedNotesFromBackupJson(backup, raw);
  assert.equal(loadNotesState().error, "");
});

test("recovery rejects stale snapshots, healthy data, and unreadable storage without writing", () => {
  const backup = createNotesBackupJson([note("restore", 10)]);
  for (const raw of ["new corruption", JSON.stringify([note("new", 20)]), "[]"]) {
    storage.set("vr-notes", raw);
    assert.throws(() => replaceCorruptedNotesFromBackupJson(backup, "old corruption"), /状态已变化或无法读取/);
    assert.equal(storage.get("vr-notes"), raw);
  }
  // Even an exact expected value cannot enable replacement of healthy records.
  assert.throws(() => replaceCorruptedNotesFromBackupJson(backup, "[]"), /状态已变化或无法读取/);
  storage.set("vr-notes", "old corruption");
  Object.defineProperty(globalThis, "localStorage", {
    value: { ...workingStorage, getItem() { throw new Error("denied"); } }, configurable: true,
  });
  assert.throws(() => replaceCorruptedNotesFromBackupJson(backup, "old corruption"), /状态已变化或无法读取/);
  assert.equal(storage.get("vr-notes"), "old corruption");
});

test("an empty validated backup can explicitly recover to an empty healthy collection", () => {
  storage.set("vr-notes", "");
  assert.deepEqual(replaceCorruptedNotesFromBackupJson(createNotesBackupJson([]), ""), []);
  assert.deepEqual(loadNotesState(), { notes: [], error: "", corruptedRaw: null });
  assert.equal(storage.get("vr-notes"), "[]");
});
