import { pcbResearch } from "./pcb.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import type { SectorResearchWorkspace } from "./types.ts";

export type { ContentBlock, ResearchTag, ResearchTagStatus, SectorResearchWorkspace, SourceRef } from "./types.ts";
export { getTagBySlug, resolveTagSlug } from "./types.ts";

/** 已启用「研究工作台」的板块注册表（未注册的仍走通用 SectorDetail） */
const WORKSPACES: Record<string, SectorResearchWorkspace> = {
  [pcbResearch.key]: pcbResearch,
};

for (const ws of Object.values(WORKSPACES)) {
  assertWorkspaceInvariants(ws);
}

export function getSectorResearchWorkspace(
  key: string | undefined,
): SectorResearchWorkspace | undefined {
  if (!key) return undefined;
  return WORKSPACES[key];
}

export function hasSectorResearchWorkspace(key: string | undefined): boolean {
  return Boolean(getSectorResearchWorkspace(key));
}

export function listSectorResearchKeys(): string[] {
  return Object.keys(WORKSPACES);
}

/** 供卡片文案：研究栏目数量 */
export function getResearchTagCount(key: string | undefined): number | undefined {
  const ws = getSectorResearchWorkspace(key);
  return ws ? ws.tags.length : undefined;
}

export function getDefaultResearchPath(key: string): string | undefined {
  const ws = getSectorResearchWorkspace(key);
  if (!ws) return undefined;
  return `/sectors/${ws.key}/${ws.defaultTag}`;
}
