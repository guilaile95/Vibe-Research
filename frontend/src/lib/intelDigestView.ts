/**
 * Pure functions for Intel Daily Digest UI state, input normalization, canonical items, and badges.
 *
 * Time integrity rules (Round 4):
 * - Never fabricate published_at from fixed dates, "now", scrape time, or page-open time.
 * - Never reverse-engineer from display fields ("07-31 10:00", "—", "2 小时前").
 * - Only accept timezone-aware ISO-8601 published_at, or ts > 0 converted to Asia/Shanghai ISO.
 * - Invalid items are filtered before prompt / chatStream / input_items construction.
 */

import type { Industry, IntelDigestInputItem } from "./api/types.ts";

export interface CanonicalDigestItem {
  title: string;
  source: string;
  url: string;
  published_at: string;
  time: string;
  summary: string;
  normalized_url: string;
}

export interface IntelDigestSourceRef {
  title: string;
  source: string;
  url: string;
  time: string;
}

export type DigestMaterialStatus = "normal" | "partial" | "unavailable";

export interface PrepareDigestItemsResult {
  canonicalItems: CanonicalDigestItem[];
  promptContext: string;
  inputItems: IntelDigestInputItem[];
  sourceRefs: IntelDigestSourceRef[];
  droppedCount: number;
  status: DigestMaterialStatus;
}

const TRACKING_PARAMS = new Set([
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
  "fbclid",
  "gclid",
  "msclkid",
  "spm",
  "_hsenc",
  "_hsmi",
  "mkt_tok",
]);

/** Absolute http/https URL with non-empty hostname. */
export function isValidHttpUrl(rawUrl: string): boolean {
  if (!rawUrl || !String(rawUrl).trim()) return false;
  try {
    const parsed = new URL(String(rawUrl).trim());
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    if (!parsed.hostname) return false;
    return true;
  } catch {
    return false;
  }
}

/**
 * True only for parseable ISO-8601 datetimes that include a timezone offset or Z.
 * Rejects bare dates ("2026-07-31") and naive local datetimes ("2026-07-31T10:00:00").
 */
export function isValidTimezoneAwareIso(value: string): boolean {
  if (!value || !String(value).trim()) return false;
  const stripped = String(value).trim();
  if (!stripped.includes("T")) return false;
  const hasTz =
    stripped.endsWith("Z") ||
    /[+-]\d{2}:\d{2}$/.test(stripped) ||
    /[+-]\d{4}$/.test(stripped);
  if (!hasTz) return false;
  const ms = Date.parse(stripped);
  return !Number.isNaN(ms);
}

const SHANGHAI_DISPLAY_FORMAT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Format a timezone-aware ISO timestamp as Beijing time; preserve invalid input. */
export function formatShanghaiTime(value: string | null | undefined): string {
  if (!value) return "未知";
  const raw = value.trim();
  if (!raw) return "未知";
  if (!isValidTimezoneAwareIso(raw)) return raw;
  return SHANGHAI_DISPLAY_FORMAT.format(new Date(raw));
}

/** Convert unix seconds to Asia/Shanghai ISO-8601 with +08:00 offset. */
export function toShanghaiIsoFromTs(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000);
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  // sv-SE → "2026-07-31 10:00:00"
  const wall = fmt.format(d).replace(" ", "T");
  return `${wall}+08:00`;
}

/**
 * Resolve authoritative published_at from a radar item.
 * Accepts only:
 *   1. Valid timezone-aware ISO published_at / iso_time
 *   2. ts > 0 (unix seconds) → Asia/Shanghai ISO
 * Never uses display time, fixed dates, or Date.now().
 */
export function resolvePublishedAt(it: Record<string, unknown>): string | null {
  const candidates = [it.published_at, it.iso_time];
  for (const c of candidates) {
    if (typeof c === "string" && isValidTimezoneAwareIso(c)) {
      return c.trim().replace(" ", "T");
    }
  }

  const rawTs = it.ts;
  const ts = typeof rawTs === "number" ? rawTs : typeof rawTs === "string" ? Number(rawTs) : NaN;
  if (Number.isFinite(ts) && ts > 0) {
    return toShanghaiIsoFromTs(ts);
  }

  return null;
}

export function normalizeUrlFrontend(rawUrl: string): string {
  if (!rawUrl) return "";
  const str = String(rawUrl).trim();
  if (!str) return "";
  try {
    const parsed = new URL(str);
    const scheme = parsed.protocol.toLowerCase();
    let hostname = parsed.hostname.toLowerCase();
    const port = parsed.port;
    const path = parsed.pathname;

    if ((scheme === "http:" && port === "80") || (scheme === "https:" && port === "443")) {
      // default port
    } else if (port) {
      hostname += `:${port}`;
    }

    const params: [string, string][] = [];
    parsed.searchParams.forEach((val, key) => {
      if (!TRACKING_PARAMS.has(key.toLowerCase())) {
        params.push([key, val]);
      }
    });
    params.sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]));

    const searchStr = params.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
    const queryPart = searchStr ? `?${searchStr}` : "";
    return `${scheme}//${hostname}${path}${queryPart}`;
  } catch {
    return str;
  }
}

/**
 * Build canonical digest materials.
 * Filters out items missing title, source, valid http(s) URL, or timezone-aware published_at
 * BEFORE prompt / chatStream / input_items construction.
 */
export function prepareDigestItems(items: Industry["items"]): PrepareDigestItemsResult {
  const rawList = items || [];
  const totalInput = rawList.length;
  const valid: CanonicalDigestItem[] = [];

  for (const raw of rawList) {
    const it = raw as unknown as Record<string, unknown>;
    const title = String(it.zh || it.title || "").trim();
    const source = String(it.source || "").trim();
    const url = String(it.url || it.source_url || "").trim();
    const published_at = resolvePublishedAt(it);

    if (!title || !source) continue;
    if (!isValidHttpUrl(url)) continue;
    if (!published_at) continue;

    const displayTime =
      (typeof it.time === "string" && it.time.trim() && it.time !== "—")
        ? it.time.trim()
        : published_at;

    valid.push({
      title,
      source,
      url,
      published_at,
      time: displayTime,
      summary: String(it.summary || it.snippet || "").trim(),
      normalized_url: normalizeUrlFrontend(url),
    });
  }

  // Sort deterministically: published_at desc, normalized_url asc, title asc, source asc
  valid.sort((a, b) => {
    if (a.published_at !== b.published_at) {
      return b.published_at.localeCompare(a.published_at);
    }
    if (a.normalized_url !== b.normalized_url) {
      return a.normalized_url.localeCompare(b.normalized_url);
    }
    if (a.title !== b.title) {
      return a.title.localeCompare(b.title);
    }
    return a.source.localeCompare(b.source);
  });

  const canonicalItems = valid.slice(0, 25);
  const droppedCount = totalInput - valid.length;

  let status: DigestMaterialStatus;
  if (canonicalItems.length === 0) {
    status = "unavailable";
  } else if (droppedCount > 0) {
    status = "partial";
  } else {
    status = "normal";
  }

  const promptContext = canonicalItems
    .map((it) => `[${it.time}] ${it.source}｜${it.title}`)
    .join("\n");

  const inputItems: IntelDigestInputItem[] = canonicalItems.map((it) => ({
    title: it.title,
    source: it.source,
    url: it.url,
    published_at: it.published_at,
    summary: it.summary || undefined,
  }));

  const sourceRefs: IntelDigestSourceRef[] = canonicalItems.map((it) => ({
    title: it.title,
    source: it.source,
    url: it.url,
    time: it.time,
  }));

  return {
    canonicalItems,
    promptContext,
    inputItems,
    sourceRefs,
    droppedCount,
    status,
  };
}

export function shouldSaveDigest(summaryText: string | null | undefined): boolean {
  if (!summaryText) return false;
  return summaryText.trim().length > 0;
}

export function digestStatusBadge(saved?: boolean, deduped?: boolean): { text: string; kind: "saved" | "deduped" | "none" } {
  if (saved && deduped) {
    return { text: "已去重", kind: "deduped" };
  }
  if (saved) {
    return { text: "已保存", kind: "saved" };
  }
  return { text: "", kind: "none" };
}

export function isSectorMatch(activeSectorKey: string, requestSectorKey: string): boolean {
  return activeSectorKey === requestSectorKey;
}
