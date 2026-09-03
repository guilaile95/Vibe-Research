// 研究记录（沉淀）—— 把 AI 复盘 / 今日要点 / 问 AI 的结果存本地，形成个人投研记录。
// 只存本地 localStorage，不上传、不进仓库。对应投研框架第 7 层「沉淀」。

import { storageGet, storageSet, storageRemove } from "@/lib/storage";

export interface Note {
  id: string;       // 记录身份
  kind: string;     // 复盘 / 今日要点 / 问AI
  title: string;    // 如「每日复盘 2026-07-04」「AI 算力 今日要点」「问 AI · 600519」
  content: string;  // markdown 正文
  ts: number;       // 保存时间戳(ms)
}

export interface NotesImportResult {
  notes: Note[];
  added: number;
  skipped: number;
}

export const NOTES_BACKUP_SCHEMA_VERSION = "vibe-notes.backup.v1";
export const NOTES_LIMIT = 200;

const KEY = "vr-notes";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function parseNote(value: unknown, index: number): Note {
  if (!isRecord(value)) throw new Error(`第 ${index + 1} 条研究记录格式无效`);
  const { id, kind, title, content, ts } = value;
  if (typeof id !== "string" || id.trim() === "") throw new Error(`第 ${index + 1} 条研究记录缺少有效 id`);
  if (typeof kind !== "string") throw new Error(`第 ${index + 1} 条研究记录 kind 无效`);
  if (typeof title !== "string") throw new Error(`第 ${index + 1} 条研究记录 title 无效`);
  if (typeof content !== "string") throw new Error(`第 ${index + 1} 条研究记录 content 无效`);
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts < 0) throw new Error(`第 ${index + 1} 条研究记录时间无效`);
  return { id, kind, title, content, ts };
}

export function loadNotes(): Note[] {
  try {
    const value = JSON.parse(storageGet(KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function persist(notes: Note[]): string {
  const serialized = JSON.stringify(notes.slice(0, NOTES_LIMIT));
  storageSet(KEY, serialized);
  return serialized;
}

export function createNotesBackupJson(
  notes: readonly Note[],
  exportedAt = new Date().toISOString(),
): string {
  return `${JSON.stringify({
    schema_version: NOTES_BACKUP_SCHEMA_VERSION,
    exported_at: exportedAt,
    notes: notes.slice(0, NOTES_LIMIT),
  }, null, 2)}\n`;
}

export function parseNotesBackupJson(raw: string): Note[] {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new Error("备份文件不是有效的 JSON");
  }
  if (!isRecord(payload)) throw new Error("备份文件格式无效");
  if (payload.schema_version !== NOTES_BACKUP_SCHEMA_VERSION) {
    throw new Error("这不是受支持的 Vibe 研究记录备份");
  }
  if (typeof payload.exported_at !== "string" || !Number.isFinite(Date.parse(payload.exported_at))) {
    throw new Error("备份文件缺少有效导出时间");
  }
  if (!Array.isArray(payload.notes)) throw new Error("备份文件缺少研究记录列表");
  if (payload.notes.length > NOTES_LIMIT) throw new Error(`单次最多导入 ${NOTES_LIMIT} 条研究记录`);

  const seen = new Set<string>();
  return payload.notes.map((value, index) => {
    const note = parseNote(value, index);
    if (seen.has(note.id)) throw new Error(`备份文件包含重复记录：${note.id}`);
    seen.add(note.id);
    return note;
  });
}

export function mergeNotesFromBackup(
  current: readonly Note[],
  imported: readonly Note[],
): NotesImportResult {
  const seen = new Set(current.map((note) => note.id));
  const addedIds = new Set<string>();
  const additions: Note[] = [];

  for (const note of imported) {
    if (seen.has(note.id)) continue;
    seen.add(note.id);
    addedIds.add(note.id);
    additions.push(note);
  }

  const notes = [...current, ...additions]
    .sort((left, right) => right.ts - left.ts || left.id.localeCompare(right.id))
    .slice(0, NOTES_LIMIT);
  const added = notes.reduce((count, note) => count + (addedIds.has(note.id) ? 1 : 0), 0);
  return {
    notes,
    added,
    skipped: imported.length - added,
  };
}

export function importNotesBackupJson(raw: string): NotesImportResult {
  const imported = parseNotesBackupJson(raw);
  const result = mergeNotesFromBackup(loadNotes(), imported);
  const serialized = persist(result.notes);
  if (storageGet(KEY) !== serialized) {
    throw new Error("浏览器无法保存导入的研究记录，请检查存储权限或空间");
  }
  return result;
}

// 新记录置顶。返回更新后的完整列表。
export function addNote(kind: string, title: string, content: string): Note[] {
  const note: Note = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    kind,
    title,
    content,
    ts: Date.now(),
  };
  const next = [note, ...loadNotes()];
  persist(next);
  return next;
}

export function deleteNote(id: string): Note[] {
  const next = loadNotes().filter((note) => note.id !== id);
  persist(next);
  return next;
}

export function clearNotes() {
  storageRemove(KEY);
}
