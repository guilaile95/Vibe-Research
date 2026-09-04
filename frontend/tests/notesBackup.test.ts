import assert from "node:assert/strict";
import test from "node:test";

import {
  NOTES_BACKUP_SCHEMA_VERSION,
  NOTES_LIMIT,
  createNotesBackupJson,
  mergeNotesFromBackup,
  parseNotesBackupJson,
  type Note,
} from "../src/lib/notes.ts";

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
