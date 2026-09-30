// 研究记录（沉淀）—— 把 AI 复盘 / 今日要点 / 问 AI 的结果存本地，形成个人投研记录。
// 只存本地 localStorage，不上传、不进仓库。对应投研框架第 7 层「沉淀」。

import { storageGetChecked, storageSetChecked, storageRemoveChecked } from "./storage.ts";

export interface Note {
  id: string;       // 记录身份
  kind: string;     // 复盘 / 今日要点 / 问AI
  title: string;    // 如「每日复盘 2026-07-04」「AI 算力 今日要点」「问 AI · 600519」
  content: string; // markdown 正文
  ts: number;      // 保存时间戳(ms)
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

function readNotes(): Note[] {
  const raw = storageGetChecked(KEY);
  let value: unknown;
  try {
    value = JSON.parse(raw ?? "[]");
  } catch {
    throw new Error("本地研究记录格式无效，原始数据已保留；请先恢复备份或修复数据");
  }
  if (!Array.isArray(value)) throw new Error("本地研究记录列表格式无效，原始数据已保留");
  const notes = value.map(parseNote);
  if (new Set(notes.map((note) => note.id)).size !== notes.length) {
    throw new Error("本地研究记录包含重复 id，原始数据已保留");
  }
  return notes;
}

export function loadNotesState(): { notes: Note[]; error: string } {
  try {
    return { notes: readNotes(), error: "" };
  } catch (error) {
    return { notes: [], error: error instanceof Error ? error.message : "无法读取研究记录" };
  }
}

export function loadNotes(): Note[] {
  return loadNotesState().notes;
}

function persist(notes: Note[]): void {
  storageSetChecked(KEY, JSON.stringify(notes.slice(0, NOTES_LIMIT)));
}

export function createNotesBackupJson(
  notes: readonly Note[],
  exportedAt = new Date().toISOString(),
): string {
  return `${JSON.stringify({
    schema_version: NOTES_BACKUP_SCHEMA_VERSION,
    exported_at: exportedAt,
    notes: notes.slice(0, NOTES_LIMIT).map(({ id, kind, title, content, ts }) => ({
      id,
      kind,
      title,
      content,
      ts,
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
  const existing = current.slice(0, NOTES_LIMIT);
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

// 新记录置顶。返回更新后的完整列表。
export function addNote(kind: string, title: string, content: string): Note[] {
  const note: Note = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    kind,
    title,
    content,
    ts: Date.now(),
  };
  const next = [note, ...readNotes()].slice(0, NOTES_LIMIT);
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
}
