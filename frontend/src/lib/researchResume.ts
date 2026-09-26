import { candidateEntryContext } from "./candidateEntryContext.ts";
import { safeInternalReturnTo } from "./internalReturnTo.ts";
import { storageGet, storageRemove, storageSet } from "./storage.ts";

const KEY = "vr-research-resume-v1";
export const RESEARCH_SECTIONS = [
  { id: "candidate-public-info", label: "查看公开资讯" },
  { id: "candidate-evidence-gap", label: "查看证据缺口" },
  { id: "candidate-existing-research", label: "继续已有研究" },
] as const;

export type ResearchVisit = { code: string; href: string; visitedAt: string };

/** Browser navigation only. Never persist evidence, portfolio state or inferred research progress. */
export function researchVisitHref(value: string): string | null {
  const internal = safeInternalReturnTo(value, "");
  if (!internal) return null;
  const url = new URL(internal, "http://localhost");
  if (!/^\/candidates\/\d{6}$/.test(url.pathname)) return null;
  const { returnTo, discoveryStrategy } = candidateEntryContext(url.searchParams);
  const query = new URLSearchParams();
  if (returnTo) query.set("return_to", returnTo);
  if (discoveryStrategy) {
    query.set("source", "discovery");
    query.set("strategy", discoveryStrategy);
  }
  const hash = RESEARCH_SECTIONS.some(({ id }) => `#${id}` === url.hash) ? url.hash : "";
  return `${url.pathname}${query.size ? `?${query}` : ""}${hash}`;
}

export function parseResearchVisits(raw: string | null): ResearchVisit[] {
  try {
    const values: unknown = JSON.parse(raw || "[]");
    if (!Array.isArray(values)) return [];
    const seen = new Set<string>();
    return values.flatMap((value): ResearchVisit[] => {
      if (!value || typeof value.href !== "string" || typeof value.visitedAt !== "string") return [];
      const href = researchVisitHref(value.href);
      if (!href || !Number.isFinite(Date.parse(value.visitedAt))) return [];
      const code = new URL(href, "http://localhost").pathname.split("/").pop()!;
      if (seen.has(code)) return [];
      seen.add(code);
      return [{ code, href, visitedAt: value.visitedAt }];
    }).slice(0, 3);
  } catch {
    return [];
  }
}

export const loadResearchVisits = (): ResearchVisit[] => parseResearchVisits(storageGet(KEY));

export function rememberResearchVisit(path: string): void {
  const href = researchVisitHref(path);
  if (!href) return;
  const code = new URL(href, "http://localhost").pathname.split("/").pop()!;
  const visits = [{ code, href, visitedAt: new Date().toISOString() }, ...loadResearchVisits().filter((visit) => visit.code !== code)].slice(0, 3);
  storageSet(KEY, JSON.stringify(visits));
}

export const clearResearchVisits = (): void => storageRemove(KEY);
