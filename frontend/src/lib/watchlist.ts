// 关注股票（自选股）—— 后端权威；localStorage 仅作一次性迁移草稿。
// KEY `vr-watchlist`：迁移成功后删除，禁止双写。

import {
  getWatchlist,
  type WatchlistAnomalyItem,
  saveWatchlist,
  importLocalWatchlist,
  type WatchlistStatus,
} from "./decisionCockpit.ts";
import type { Quote } from "./api.ts";

const KEY = "vr-watchlist";

export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

export function addCodes(
  existing: string[],
  raw: string,
): { next: string[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.includes(c));
  return { next: [...existing, ...incoming], added: incoming.length };
}

export type WatchlistSort = "anomaly" | "watchlist" | "change" | "amount";

export function filterAndSortWatchlistCodes(
  codes: string[],
  quotes: Record<string, Quote>,
  anomalies: WatchlistAnomalyItem[],
  sort: WatchlistSort,
  onlyAnomalies: boolean,
): string[] {
  const anomalyCodes = new Set(anomalies.map((item) => item.code));
  const rows = codes
    .map((code, index) => ({ code, index }))
    .filter(({ code }) => !onlyAnomalies || anomalyCodes.has(code));
  if (sort === "watchlist") return rows.map(({ code }) => code);
  const score = (code: string) => {
    if (sort === "anomaly") return anomalyCodes.has(code) ? 1 : 0;
    const value = sort === "amount" ? quotes[code]?.amount_wan : quotes[code]?.change_pct;
    return value == null ? Number.NEGATIVE_INFINITY : sort === "change" ? Math.abs(value) : value;
  };
  return rows
    .sort((a, b) => score(b.code) - score(a.code) || a.index - b.index)
    .map(({ code }) => code);
}

/** 读取残留的 localStorage 草稿（迁移前）；不作为权威源。 */
export function loadLocalDraft(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v)
      ? v.filter((c: unknown) => typeof c === "string" && /^\d{6}$/.test(c))
      : [];
  } catch {
    return [];
  }
}

/** 迁移成功后删除 localStorage KEY，禁止残留双写。 */
export function clearLocalDraft(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function hasLocalDraft(): boolean {
  return loadLocalDraft().length > 0;
}

/**
 * 一次性：若存在 localStorage 草稿则 etag-aware 并入后端，成功后删除 KEY。
 * 后端已有数据时 merge；冲突时抛错由调用方处理。
 */
export async function migrateLocalWatchlistOnce(
  expectedEtag?: string | null,
): Promise<{
  migrated: boolean;
  codes: string[];
  etag: string | null;
  added: string[];
}> {
  const local = loadLocalDraft();
  if (local.length === 0) {
    const st = await getWatchlist();
    const codes = st.status === "valid" ? st.data.codes : [];
    return {
      migrated: false,
      codes,
      etag: st.status === "valid" ? st.etag : null,
      added: [],
    };
  }
  const result = await importLocalWatchlist(local, expectedEtag ?? undefined);
  clearLocalDraft();
  return {
    migrated: true,
    codes: result.codes,
    etag: result.etag,
    added: result.added,
  };
}

function validCodes(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 50
    && value.every(code => typeof code === "string" && /^\d{6}$/.test(code))
    && new Set(value).size === value.length;
}
function validEtag(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{16}$/.test(value);
}
function assertWatchStatus(value: WatchlistStatus): void {
  if (!value || typeof value !== "object") throw new Error("自选读取响应无效，请重新读取");
  if (value.status === "valid") {
    if (!value.data || !validCodes(value.data.codes) || !validEtag(value.etag))
      throw new Error("自选代码或版本响应无效，请重新读取");
  } else if (!["not_configured", "corrupted"].includes(value.status) || value.data !== null || value.etag !== null) {
    throw new Error("自选状态响应无效，请重新读取");
  }
}

/** 权威加载：先尝试迁移，再读后端。 */
export async function loadWatchAuthoritative(): Promise<{
  codes: string[];
  etag: string | null;
  status: WatchlistStatus["status"];
  migrated: boolean;
  migrationError?: string;
}> {
  let st = await getWatchlist();
  assertWatchStatus(st);
  let migrated = false;
  let migrationError: string | undefined;
  if (hasLocalDraft()) {
    try {
      const m = await migrateLocalWatchlistOnce(
        st.status === "valid" ? st.etag : undefined,
      );
      migrated = m.migrated;
    } catch (error) {
      // 迁移失败时仍返回后端状态；草稿保留供用户重试
      migrationError = error instanceof Error ? error.message : "本地草稿导入失败，请重试";
    }
    // A failed read after a successful import is not a retained-draft failure.
    if (migrated) { st = await getWatchlist(); assertWatchStatus(st); }
  }
  if (st.status === "valid") {
    return {
      codes: st.data.codes,
      etag: st.etag,
      status: st.status,
      migrated,
      migrationError,
    };
  }
  return { codes: [], etag: null, status: st.status, migrated, migrationError };
}

/** 后端权威保存（无 localStorage 双写）。 */
export async function saveWatchAuthoritative(
  codes: string[],
  expectedEtag?: string | null,
): Promise<{ codes: string[]; etag: string }> {
  const intended = Array.from(new Set(codes));
  if (!validCodes(intended)) throw new Error("自选保存输入无效");
  const r = await saveWatchlist(intended, expectedEtag ?? undefined);
  if (!r || !validCodes(r.codes) || !validEtag(r.etag)
      || JSON.stringify(r.codes) !== JSON.stringify(intended)) {
    throw new Error("自选保存回执无效，尚未确认成功；输入已保留，请重新读取后预览");
  }
  clearLocalDraft();
  return { codes: r.codes, etag: r.etag };
}

// ---------------------------------------------------------------------------
// 兼容旧同步 API：仅读 local 草稿（调用方应尽快改异步权威 API）
// ---------------------------------------------------------------------------

/** @deprecated 仅返回 local 草稿，不读后端。请用 loadWatchAuthoritative。 */
export function loadWatch(): string[] {
  return loadLocalDraft();
}

/** @deprecated 禁止双写权威路径；仅写 local 草稿。请用 saveWatchAuthoritative。 */
export function saveWatch(codes: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(codes));
  } catch {
    /* ignore */
  }
}
