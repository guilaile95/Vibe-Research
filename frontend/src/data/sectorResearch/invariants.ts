/**
 * 纯函数：供 node:test 与运行时共用的工作台配置校验。
 * 不依赖 React。
 */
import type { SectorResearchWorkspace } from "./types.ts";
import { getSectorResearchWorkspace, listSectorResearchKeys } from "./index.ts";
import { pcbResearch } from "./pcb.ts";

export type WorkspaceCheckResult = {
  ok: boolean;
  errors: string[];
};

export function checkWorkspace(ws: SectorResearchWorkspace): WorkspaceCheckResult {
  const errors: string[] = [];
  if (!ws.key) errors.push("missing key");
  if (!ws.tags.length) errors.push("no tags");
  const slugs = ws.tags.map((t) => t.slug);
  if (new Set(slugs).size !== slugs.length) errors.push("duplicate tag slugs");
  if (!slugs.includes(ws.defaultTag)) {
    errors.push(`defaultTag "${ws.defaultTag}" not in tags`);
  }
  for (const t of ws.tags) {
    if (!t.slug || !t.label || !t.title) {
      errors.push(`tag incomplete: ${t.slug || "(empty slug)"}`);
    }
    if (!t.blocks.length) errors.push(`tag "${t.slug}" has no blocks`);
  }
  return { ok: errors.length === 0, errors };
}

export function expectedPcbTagSlugs(): string[] {
  return [
    "overview",
    "technology",
    "value",
    "copper-midplane",
    "industry",
    "pricing-power",
  ];
}

export function expectedPcbTagLabels(): string[] {
  return ["总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图"];
}

/** PCB 六 Tag 完整性快照（供测试锁定顺序与命名） */
export function pcbConfigSnapshot() {
  return {
    key: pcbResearch.key,
    defaultTag: pcbResearch.defaultTag,
    tagCount: pcbResearch.tags.length,
    slugs: pcbResearch.tags.map((t) => t.slug),
    labels: pcbResearch.tags.map((t) => t.label),
    allPlaceholder: pcbResearch.tags.every((t) => t.status === "placeholder"),
  };
}

export function resolveOrFallback(
  key: string,
  slug: string | undefined,
): { workspaceKey: string; tagSlug: string; redirected: boolean } | null {
  const ws = getSectorResearchWorkspace(key);
  if (!ws) return null;
  const resolved = slug && ws.tags.some((t) => t.slug === slug) ? slug : ws.defaultTag;
  return {
    workspaceKey: ws.key,
    tagSlug: resolved,
    redirected: resolved !== slug,
  };
}

export function registeredResearchKeys(): string[] {
  return listSectorResearchKeys();
}
