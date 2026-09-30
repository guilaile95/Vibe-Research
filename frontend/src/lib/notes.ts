// 研究记录（沉淀）—— 把 AI 复盘 / 今日要点 / 问 AI 的结果存本地，形成个人投研记录。
// 只存本地 localStorage，不上传、不进仓库。对应投研框架第 7 层「沉淀」。

import { storageGetChecked, storageSetChecked, storageRemoveChecked } from "./storage.ts";
import { parseNoteResearchMetadata, type NoteResearchMetadata } from "./researchNote.ts";

export interface Note {
  id: string;       // 记录身份
  kind: string;     // 复盘 / 今日要点 / 问AI
  title: string;    // 如「每日复盘 2026-07-04」「AI 算力 今日要点」「问 AI · 600519」
  content: string; // markdown 正文
  ts: number;      // 保存时间戳(ms)
  research?: NoteResearchMetadata;
}

export interface NotesImportResult {
  notes: Note[];
  added: number;
  skipped: number;
}

export interface NotesState {
  notes: Note[];
  error: string;
  // null means healthy or unreadable storage; an empty string is still corrupt data.
  corruptedRaw: string | null;
}

export const NOTES_BACKUP_SCHEMA_VERSION = "vibe-notes.backup.v1";
export const NOTES_LIMIT = 200;
export const NOTES_CHANGED_EVENT = "vr-notes-changed";

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
  return { id, kind, title, content, ts, ...(value.research === undefined ? {} : { research: parseNoteResearchMetadata(value.research) }) };
}

function parseStoredNotes(raw: string | null): Note[] {
  let value: unknown;
  try {
    value = JSON.parse(raw ?? "[]");
  } catch {
    throw new Error("本地研究记录格式无效，原始数据已保留");
  }
  if (!Array.isArray(value)) throw new Error("本地研究记录列表格式无效，原始数据已保留");
  const notes = value.map(parseNote);
  if (new Set(notes.map((note) => note.id)).size !== notes.length) {
    throw new Error("本地研究记录包含重复 id，原始数据已保留");
  }
  return notes;
}

function readNotes(): Note[] {
  return parseStoredNotes(storageGetChecked(KEY));
}

export function loadNotesState(): NotesState {
  let raw: string | null;
  try {
    raw = storageGetChecked(KEY);
  } catch (error) {
    return { notes: [], error: error instanceof Error ? error.message : "无法读取研究记录", corruptedRaw: null };
  }
  try {
    return { notes: parseStoredNotes(raw), error: "", corruptedRaw: null };
  } catch (error) {
    return { notes: [], error: error instanceof Error ? error.message : "研究记录格式无效", corruptedRaw: raw };
  }
}

export function loadNotes(): Note[] {
  return loadNotesState().notes;
}

function persist(notes: Note[]): void {
  storageSetChecked(KEY, JSON.stringify(notes));
  if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTES_CHANGED_EVENT));
}

export function createNotesBackupJson(
  notes: readonly Note[],
  exportedAt = new Date().toISOString(),
): string {
  if (notes.length > NOTES_LIMIT) throw new Error(`本地记录超过 ${NOTES_LIMIT} 条，无法生成完整的标准备份；请先保留原始 vr-notes 数据，未导出截断备份。`);
  return `${JSON.stringify({
    schema_version: NOTES_BACKUP_SCHEMA_VERSION,
    exported_at: exportedAt,
    notes: notes.map(({ id, kind, title, content, ts, research }) => ({
      id,
      kind,
      title,
      content,
      ts,
      ...(research === undefined ? {} : { research: parseNoteResearchMetadata(research) }),
    })),
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
  const existing = [...current];
  const seen = new Set(existing.map((note) => note.id));
  const additions: Note[] = [];

  for (const note of imported) {
    if (seen.has(note.id)) continue;
    seen.add(note.id);
    additions.push(note);
  }

  const available = Math.max(0, NOTES_LIMIT - existing.length);
  const accepted = additions
    .sort((left, right) => right.ts - left.ts || left.id.localeCompare(right.id))
    .slice(0, available);
  const notes = [...existing, ...accepted]
    .sort((left, right) => right.ts - left.ts || left.id.localeCompare(right.id));

  return {
    notes,
    added: accepted.length,
    skipped: imported.length - accepted.length,
  };
}

export function importNotesBackupJson(raw: string): NotesImportResult {
  const imported = parseNotesBackupJson(raw);
  const result = mergeNotesFromBackup(readNotes(), imported);
  persist(result.notes);
  return result;
}

// Recovery is deliberately separate from merge import. The caller confirms replacement
// after validating the backup; stale views must never replace newer or healthy storage.
export function replaceCorruptedNotesFromBackupJson(raw: string, expectedCorruptedRaw: string): Note[] {
  const imported = parseNotesBackupJson(raw);
  const current = loadNotesState();
  if (current.corruptedRaw === null || current.corruptedRaw !== expectedCorruptedRaw) {
    throw new Error("本地研究记录状态已变化或无法读取，请刷新后重试；未替换任何数据");
  }
  // A single setItem is atomic on quota failure. Never remove the original first.
  persist(imported);
  return imported;
}

// 新记录置顶。返回更新后的完整列表。
export function addNote(kind: string, title: string, content: string, research?: NoteResearchMetadata): Note[] {
  const note: Note = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    kind,
    title,
    content,
    ts: Date.now(),
    ...(research === undefined ? {} : { research: parseNoteResearchMetadata(research) }),
  };
  const current = readNotes();
  if (current.length >= NOTES_LIMIT) {
    throw new Error(`研究记录已达到 ${NOTES_LIMIT} 条上限；请先在研究记录页导出备份，再手动清理不需要的记录。已有记录未被删除。`);
  }
  const next = [note, ...current];
  persist(next);
  return next;
}

export function deleteNote(id: string): Note[] {
  const next = readNotes().filter((note) => note.id !== id);
  persist(next);
  return next;
}

export function clearNotes() {
  storageRemoveChecked(KEY);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTES_CHANGED_EVENT));
}
