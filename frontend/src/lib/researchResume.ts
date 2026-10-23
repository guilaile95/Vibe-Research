import { candidateEntryContext } from "./candidateEntryContext.ts";
import { safeInternalReturnTo } from "./internalReturnTo.ts";
import { storageGet, storageRemove, storageSet } from "./storage.ts";

const KEY = "vr-research-resume-v1";
export const RESEARCH_SECTIONS = [
  { id: "candidate-public-info", label: "查看公开资讯" },
  { id: "candidate-evidence-gap", label: "查看证据缺口" },
  { id: "candidate-research-check", label: "问题与材料核对" },
  { id: "candidate-research-note", label: "轻量笔记与 AI 草稿" },
  { id: "candidate-existing-research", label: "候选投资计划" },
] as const;

export type ResearchVisit = { code: string; href: string; visitedAt: string };

export type ResearchSelection =
  | { status: "absent" }
  | { status: "invalid" }
  | { status: "selected"; questionId: string; roundId: string | null };

/** URL is only a locator. Ownership is checked against the validated local snapshot. */
export function parseResearchSelection(search: string): ResearchSelection {
  const params = new URLSearchParams(search);
  const questions = params.getAll("question"), rounds = params.getAll("round");
  if (!questions.length && !rounds.length) return { status: "absent" };
  if (questions.length !== 1 || rounds.length > 1) return { status: "invalid" };
  try {
    for (const entry of search.replace(/^\?/, "").split("&")) {
      const [key, ...parts] = entry.split("=");
      if (["question", "round"].includes(decodeURIComponent(key.replace(/\+/g, " ")))) {
        // URLSearchParams replaces malformed UTF-8; never silently change saved identity.
        decodeURIComponent(parts.join("=").replace(/\+/g, " "));
      }
    }
  } catch { return { status: "invalid" }; }
  if ([...questions, ...rounds].some(value => !value.trim() || value.length > 256)) return { status: "invalid" };
  return { status: "selected", questionId: questions[0], roundId: rounds[0] ?? null };
}

export function researchSelectionHref(path: string, questionId: string | null, roundId: string | null = null): string | null {
  const internal = safeInternalReturnTo(path, "");
  if (!internal) return null;
  const url = new URL(internal, "http://localhost");
  url.searchParams.delete("question"); url.searchParams.delete("round");
  if (questionId !== null) url.searchParams.set("question", questionId);
  if (roundId !== null) url.searchParams.set("round", roundId);
  return researchVisitHref(`${url.pathname}${url.search}${url.hash}`);
}

/** Same-stock read-position changes retain both editors. A question change affects only the check draft. */
export function researchNavigationRisk(current: { pathname: string; search: string }, next: { pathname: string; search: string }): "none" | "question" | "page" {
  if (current.pathname !== next.pathname) return "page";
  if (current.search === next.search) return "none";
  const context = (search: string) => { const params = new URLSearchParams(search); params.delete("question"); params.delete("round"); params.sort(); return params.toString(); };
  if (context(current.search) !== context(next.search)) return "page";
  const before = parseResearchSelection(current.search), after = parseResearchSelection(next.search);
  if (before.status === "invalid" || after.status === "invalid") return "question";
  return (before.status === "selected" ? before.questionId : null) === (after.status === "selected" ? after.questionId : null) ? "none" : "question";
}

export function sameStockCandidateReturn(value: string, code: string): string | null {
  const href = researchVisitHref(value);
  return href && new URL(href, "http://localhost").pathname === `/candidates/${code}` ? href : null;
}


/** Browser navigation only. Never persist evidence, portfolio state or inferred research progress. */
export function researchVisitHref(value: string): string | null {
  const internal = safeInternalReturnTo(value, "");
  if (!internal) return null;
  const url = new URL(internal, "http://localhost");
  if (!/^\/candidates\/\d{6}$/.test(url.pathname)) return null;
  const selection = parseResearchSelection(url.search);
  if (selection.status === "invalid") return null;
  const { returnTo, discoveryStrategy } = candidateEntryContext(url.searchParams);
  const query = new URLSearchParams();
  if (returnTo) query.set("return_to", returnTo);
  if (discoveryStrategy) {
    query.set("source", "discovery");
    query.set("strategy", discoveryStrategy);
  }
  if (selection.status === "selected") {
    query.set("question", selection.questionId);
    if (selection.roundId !== null) query.set("round", selection.roundId);
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
