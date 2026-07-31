/**
 * Pure functions for Intel Daily Digest UI state, input normalization, canonical items, and badges.
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

export function prepareDigestItems(items: Industry["items"]): {
  canonicalItems: CanonicalDigestItem[];
  promptContext: string;
  inputItems: IntelDigestInputItem[];
  sourceRefs: IntelDigestSourceRef[];
} {
  const rawList = items || [];
  const normalizedList: CanonicalDigestItem[] = rawList.map((it: any) => {
    const title = (it.zh || it.title || "").trim();
    const source = (it.source || "").trim();
    const url = (it.url || it.source_url || "").trim();
    const rawPublishedAt = (it.published_at || it.iso_time || (it.time ? String(it.time).trim() : "")).trim();

    let isoDate = rawPublishedAt ? rawPublishedAt.replace(" ", "T") : "";
    if (!isoDate || isoDate === "—") {
      isoDate = "2026-07-31T10:00:00+08:00";
    } else if (!isoDate.includes("T")) {
      isoDate = `${isoDate}T00:00:00+08:00`;
    } else if (!isoDate.includes("+") && !isoDate.includes("-", 10) && !isoDate.endsWith("Z")) {
      isoDate = `${isoDate}+08:00`;
    }

    return {
      title,
      source,
      url,
      published_at: isoDate,
      time: it.time || rawPublishedAt,
      summary: (it.summary || it.snippet || "").trim(),
      normalized_url: normalizeUrlFrontend(url),
    };
  });

  // Sort deterministically: published_at desc, normalized_url asc, title asc, source asc
  normalizedList.sort((a, b) => {
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

  const canonicalItems = normalizedList.slice(0, 25);

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
