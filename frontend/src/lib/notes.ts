// 研究记录（沉淀）—— 把 AI 复盘 / 今日要点 / 问 AI 的结果存本地，形成个人投研记录。
// 只存本地 localStorage，不上传、不进仓库。对应投研框架第 7 层「沉淀」。

import { storageGetChecked, storageSetChecked } from "./storage.ts";
import { parseNoteResearchMetadata, type NoteResearchMetadata } from "./researchNote.ts";

import { parseNoteGeneration, type NoteGeneration } from "./noteGeneration.ts";

export interface Note {
  id: string;       // 记录身份
  kind: string;     // 复盘 / 今日要点 / 问AI
  title: string;    // 如「每日复盘 2026-07-04」「AI 算力 今日要点」「问 AI · 600519」
  content: string; // markdown 正文
  ts: number;      // 保存时间戳(ms)
  research?: NoteResearchMetadata;
  generation?: NoteGeneration;
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

export const NOTES_GENERATION_BACKUP_SCHEMA_VERSION = "vibe-notes.backup.v2";

const KEY = "vr-notes";
export const NOTES_STORAGE_KEY = "vr-notes.v2";
export const NOTES_WRITE_LOCK = "vibe-research.notes.v2";
const STORAGE_SCHEMA = "vibe-notes.storage.v2";
class LegacyNotesConflict extends Error {}

// New versions never write the legacy key: a non-cooperating old tab cannot
// overwrite acknowledged v2 saves. Its subsequent writes block us conservatively.
function storedState(): { raw: string | null; legacyRaw: string | null } {
  const legacyRaw = storageGetChecked(KEY);
  const raw = storageGetChecked(NOTES_STORAGE_KEY);
  if (raw === null) return { raw: legacyRaw, legacyRaw };
  let envelope: unknown;
  try { envelope = JSON.parse(raw); } catch { throw new Error("新版研究记录格式无效，原始数据已保留"); }
  if (!isRecord(envelope) || envelope.schema !== STORAGE_SCHEMA || !(envelope.legacyRaw === null || typeof envelope.legacyRaw === "string") || !Array.isArray(envelope.notes)) {
    throw new Error("新版研究记录格式无效，原始数据已保留");
  }
  if (envelope.legacyRaw !== legacyRaw) throw new LegacyNotesConflict("旧版本页面修改了旧笔记。新版与旧版原始数据均已保留；请关闭旧版本页面，分别备份并核对后再处理，未合并或覆盖。请勿清除浏览器数据。");
  return { raw: JSON.stringify(envelope.notes), legacyRaw };
}

/** No unlocked fallback. Every add/delete/import/recovery/clear shares this lock. */
let writeLegacyRaw: string | null = null;
async function mutateNotes<T>(work: () => T): Promise<T> {
  const locks = globalThis.navigator?.locks;
  if (!locks?.request) throw new Error("当前浏览器不支持安全的多页面笔记保存（Web Locks）；未写入。请使用支持此功能的安全上下文浏览器，并关闭旧版本页面。");
  return locks.request(NOTES_WRITE_LOCK, { mode: "exclusive" }, () => {
    writeLegacyRaw = storageGetChecked(KEY);
    return work();
  });
}

/** Raw preservation archive, deliberately not accepted as an ordinary notes backup. */
export function notesRecoveryArchive(): string {
  return JSON.stringify({ schema: "vibe-notes.recovery-archive.v1", legacyRaw: storageGetChecked(KEY), currentRaw: storageGetChecked(NOTES_STORAGE_KEY) }, null, 2);
}

export function notesSourceRaw(): string | null { return storedState().raw; }

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
  return { id, kind, title, content, ts, ...(value.research === undefined ? {} : { research: parseNoteResearchMetadata(value.research) }), ...(value.generation === undefined ? {} : { generation: parseNoteGeneration(value.generation) }) };
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
  return parseStoredNotes(notesSourceRaw());
}

export function loadNotesState(): NotesState {
  let raw: string | null;
  try {
    raw = notesSourceRaw();
  } catch (error) {
    let corruptedRaw: string | null = null;
    if (!(error instanceof LegacyNotesConflict)) {
      try { const candidate = storageGetChecked(NOTES_STORAGE_KEY); if (candidate !== null && error instanceof Error && error.message.includes("格式无效")) corruptedRaw = candidate; } catch { /* unreadable is not corruption */ }
    }
    return { notes: [], error: error instanceof Error ? error.message : "无法读取研究记录", corruptedRaw };
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
  // Re-read while holding the lock. Recovery may replace corrupt v2 bytes only
  // after its explicit expected-raw check; legacy bytes remain untouched.
  const legacyRaw = writeLegacyRaw;
  if (storageGetChecked(KEY) !== legacyRaw) throw new LegacyNotesConflict("旧版本笔记已变化；未覆盖，请关闭旧页面并保留两份数据。");
  storageSetChecked(NOTES_STORAGE_KEY, JSON.stringify({ schema: STORAGE_SCHEMA, legacyRaw, notes }));
  if (storageGetChecked(KEY) !== legacyRaw) throw new LegacyNotesConflict("旧版本页面同时修改了笔记；两份原始数据已保留，请分别备份核对。此次保存状态不确定，未显示保存成功。");
  if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTES_CHANGED_EVENT));
}

export function createNotesBackupJson(
  notes: readonly Note[],
  exportedAt = new Date().toISOString(),
): string {
  if (notes.length > NOTES_LIMIT) throw new Error(`本地记录超过 ${NOTES_LIMIT} 条，无法生成完整的标准备份；请先保留原始 vr-notes 数据，未导出截断备份。`);
  return `${JSON.stringify({
    schema_version: notes.some(note => note.generation !== undefined) ? NOTES_GENERATION_BACKUP_SCHEMA_VERSION : NOTES_BACKUP_SCHEMA_VERSION,
    exported_at: exportedAt,
    notes: notes.map(({ id, kind, title, content, ts, research, generation }) => ({
      id,
      kind,
      title,
      content,
      ts,
      ...(research === undefined ? {} : { research: parseNoteResearchMetadata(research) }),
    ...(generation === undefined ? {} : { generation: parseNoteGeneration(generation) }),
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
  if (payload.schema_version !== NOTES_BACKUP_SCHEMA_VERSION && payload.schema_version !== NOTES_GENERATION_BACKUP_SCHEMA_VERSION) {
    throw new Error("这不是受支持的 Vibe 研究记录备份");
  }
  if (typeof payload.exported_at !== "string" || !Number.isFinite(Date.parse(payload.exported_at))) {
    throw new Error("备份文件缺少有效导出时间");
  }
  if (!Array.isArray(payload.notes)) throw new Error("备份文件缺少研究记录列表");
  if (payload.notes.length > NOTES_LIMIT) throw new Error(`单次最多导入 ${NOTES_LIMIT} 条研究记录`);

  const seen = new Set<string>();
  return payload.notes.map((value, index) => {
    if (payload.schema_version === NOTES_BACKUP_SCHEMA_VERSION && isRecord(value) && value.generation !== undefined) {
      throw new Error("包含生成依据的备份必须使用 v2；未导入降级文件");
    }
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

export async function importNotesBackupJson(raw: string): Promise<NotesImportResult> {
  return mutateNotes(() => {
    const imported = parseNotesBackupJson(raw);
    const result = mergeNotesFromBackup(readNotes(), imported);
    persist(result.notes);
    return result;
  });
}

// Recovery is deliberately separate from merge import. The caller confirms replacement
// after validating the backup; stale views must never replace newer or healthy storage.
export async function replaceCorruptedNotesFromBackupJson(raw: string, expectedCorruptedRaw: string): Promise<Note[]> {
  return mutateNotes(() => {
    const imported = parseNotesBackupJson(raw);
    const current = loadNotesState();
    if (current.corruptedRaw === null || current.corruptedRaw !== expectedCorruptedRaw) {
      throw new Error("本地研究记录状态已变化或无法读取，请刷新后重试；未替换任何数据");
    }
    // A single setItem is atomic on quota failure. Never remove the original first.
    persist(imported);
    return imported;
  });
}

// 新记录置顶。返回更新后的完整列表。
export async function addNote(kind: string, title: string, content: string, research?: NoteResearchMetadata, generation?: NoteGeneration): Promise<Note[]> {
  return mutateNotes(() => {
    const note: Note = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      kind,
      title,
      content,
      ts: Date.now(),
      ...(research === undefined ? {} : { research: parseNoteResearchMetadata(research) }),
      ...(generation === undefined ? {} : { generation: parseNoteGeneration(generation) }),
    };
    const current = readNotes();
    if (current.length >= NOTES_LIMIT) {
      throw new Error(`研究记录已达到 ${NOTES_LIMIT} 条上限；请先在研究记录页导出备份，再手动清理不需要的记录。已有记录未被删除。`);
    }
    const next = [note, ...current];
    persist(next);
    return next;
  });
}

export async function deleteNote(id: string): Promise<Note[]> {
  return mutateNotes(() => {
    const next = readNotes().filter((note) => note.id !== id);
    persist(next);
    return next;
  });
}

export async function clearNotes(): Promise<void> {
  return mutateNotes(() => {
    readNotes(); // Do not erase corruption or revive a conflicting legacy collection.
    persist([]); // Keep the v2 marker so legacy notes cannot reappear after clearing.
  });
}

/** Browser-local, read-only search; never sends query or content to a server/model. */
export function filterResearchNotes(notes: readonly Note[], kind: string, query: string, securityCode = ""): { notes: Note[]; error: string } {
  if (query.length > 120) return { notes: [], error: "搜索词超过120字符，未执行搜索" };
  const candidates = notes.filter(note => (!kind || note.kind === kind) && (!securityCode || note.research?.securityCode === securityCode));
  const term = query.trim().toLocaleLowerCase();
  if (!term) return { notes: candidates, error: "" };
  let scanned = 0;
  const result: Note[] = [];
  for (const note of candidates) {
    const fields = [note.title, note.kind, note.content, note.research?.securityCode ?? "", note.research?.question ?? "", note.research?.tentativeView ?? "", note.research?.contraryEvidence ?? "", note.research?.nextQuestion ?? ""];
    scanned += fields.reduce((total, field) => total + field.length, 0);
    if (scanned > 4_000_000) return { notes: [], error: "所选记录超过400万字符搜索上限，未展示截断结果；请先缩小类型或证券范围" };
    if (fields.some(field => field.toLocaleLowerCase().includes(term))) result.push(note);
  }
  return { notes: result, error: "" };
}
