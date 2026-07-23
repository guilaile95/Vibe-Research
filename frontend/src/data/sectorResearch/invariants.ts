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
  const sourceIds = new Set(ws.sources.map((s) => s.id));
  for (const t of ws.tags) {
    if (!t.slug || !t.label || !t.title) {
      errors.push(`tag incomplete: ${t.slug || "(empty slug)"}`);
    }
    if (!t.blocks.length) errors.push(`tag "${t.slug}" has no blocks`);
    errors.push(...checkBlockInvariants(t.slug, t.blocks, sourceIds));
  }
  return { ok: errors.length === 0, errors };
}

/** 校验内容块：sourceIds 必须存在于 workspace.sources；table 行列数与 headers 一致；source id 不重复。 */
export function checkBlockInvariants(
  tagSlug: string,
  blocks: import("./types.ts").ContentBlock[],
  sourceIds: Set<string>,
): string[] {
  const errors: string[] = [];
  for (const block of blocks) {
    if (block.type === "placeholder") continue;
    const ids = block.sourceIds;
    if (ids) {
      if (new Set(ids).size !== ids.length) {
        errors.push(`tag "${tagSlug}" ${block.type} has duplicate sourceIds`);
      }
      for (const id of ids) {
        if (!sourceIds.has(id)) {
          errors.push(`tag "${tagSlug}" ${block.type} sourceId "${id}" not in workspace.sources`);
        }
      }
    }
    if (block.type === "table" || block.type === "compareTable") {
      const expected = block.headers.length;
      for (const row of block.rows) {
        if (row.length !== expected) {
          errors.push(`tag "${tagSlug}" ${block.type} row length ${row.length} != headers ${expected}`);
        }
      }
    }
  }
  return errors;
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
