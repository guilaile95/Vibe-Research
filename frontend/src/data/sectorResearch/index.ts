/**
 * 板块研究工作台注册表 —— 同步元数据 + 异步内容加载。
 *
 * 同步层（sectorMeta.ts）仅含 key/label/fullName/tagline/defaultTag 与 tags 骨架
 * （slug/label/title/status，不含正文块），供路由守卫、板块中心列表与详情页外壳使用，
 * 不再进入首屏 bundle。
 *
 * 研究正文块（blocks）与来源池（sources）体量大，通过 loadSectorResearchWorkspace
 * 按需动态 import：仅在进入具体板块详情页时加载该板块内容，避免首屏一次性加载 20 份正文。
 */
import {
  getDefaultResearchPath,
  getResearchTagCount,
  getSectorMeta,
  hasSectorResearchWorkspace,
  listSectorResearchKeys,
  resolveSectorTagMeta,
} from "./sectorMeta.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import type { SectorResearchWorkspace } from "./types.ts";

export type {
  ContentBlock,
  ResearchTag,
  ResearchTagStatus,
  SectorResearchWorkspace,
  SourceRef,
} from "./types.ts";
export { getTagBySlug, resolveTagSlug } from "./types.ts";
export {
  getDefaultResearchPath,
  getResearchTagCount,
  getSectorMeta,
  hasSectorResearchWorkspace,
  listSectorResearchKeys,
  resolveSectorTagMeta,
};

/** 按板块 key 的按需内容加载器（动态 import → 不进首屏）。 */
const CONTENT_LOADERS: Record<string, () => Promise<SectorResearchWorkspace>> = {
  pcb: () => import("./pcb.ts").then((m) => m.pcbResearch),
  humanoid: () => import("./humanoid.ts").then((m) => m.humanoidResearch),
  "ai-computing": () => import("./ai-computing.ts").then((m) => m.aiComputingResearch),
  hbm: () => import("./hbm.ts").then((m) => m.hbmResearch),
  cpo: () => import("./cpo.ts").then((m) => m.cpoResearch),
  "smart-driving": () => import("./smart-driving.ts").then((m) => m.smartDrivingResearch),
  "low-altitude": () => import("./low-altitude.ts").then((m) => m.lowAltitudeResearch),
  semiconductor: () =>
    import("./semiconductor.ts").then((m) => m.semiconductorResearch),
  "solid-state-battery": () =>
    import("./solid-state-battery.ts").then((m) => m.ssBatteryResearch),
  "innovative-drug": () =>
    import("./innovative-drug/innovative-drug.ts").then((m) => m.innovativeDrugResearch),
  fusion: () => import("./fusion/fusion.ts").then((m) => m.fusionResearch),
  defense: () => import("./defense/defense.ts").then((m) => m.defenseResearch),
  "business-space": () =>
    import("./business-space/business-space.ts").then((m) => m.businessSpaceResearch),
  "power-grid": () => import("./power-grid/power-grid.ts").then((m) => m.powerGridResearch),
  "ai-application": () =>
    import("./ai-application/ai-application.ts").then((m) => m.aiApplicationResearch),
  "ai-hardware": () => import("./ai-hardware/ai-hardware.ts").then((m) => m.aiHardwareResearch),
  "energy-storage": () =>
    import("./energy-storage/energy-storage.ts").then((m) => m.energyStorageResearch),
  "data-element": () =>
    import("./data-element/data-element.ts").then((m) => m.dataElementResearch),
  resources: () => import("./resources/resources.ts").then((m) => m.resourcesResearch),
  "ai-pharma": () => import("./ai-pharma/ai-pharma.ts").then((m) => m.aiPharmaResearch),
};

/**
 * 按需加载某板块的完整研究工作台（含正文块与来源池）。
 * 返回 Promise；未注册板块返回 undefined。应在详情页 useEffect 中调用，避免首屏加载。
 */
export async function loadSectorResearchWorkspace(
  key: string | undefined,
): Promise<SectorResearchWorkspace | undefined> {
  if (!key) return undefined;
  if (!hasSectorResearchWorkspace(key)) return undefined;
  const loader = CONTENT_LOADERS[key];
  const ws = await loader();
  assertWorkspaceInvariants(ws);
  return ws;
}
