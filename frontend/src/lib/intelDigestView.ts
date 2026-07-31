/**
 * Pure functions for Intel Daily Digest UI state, input normalization, and badges.
 */

import type { Industry, IntelDigestInputItem } from "./api/types.ts";

export interface IntelDigestSourceRef {
  title: string;
  source: string;
  url: string;
  time: string;
}

export function buildDigestSourceRefs(items: Industry["items"]): IntelDigestSourceRef[] {
  return (items || []).slice(0, 25).map((it) => ({
    title: it.zh || it.title || "",
    source: it.source || "",
    url: it.url || "",
    time: it.time || "",
  }));
}

export function buildDigestInputItems(items: Industry["items"]): IntelDigestInputItem[] {
  return (items || []).slice(0, 25).map((it) => ({
    title: it.zh || it.title || "",
    source: it.source || "",
    url: it.url || "",
    published_at: it.time || "",
  }));
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
