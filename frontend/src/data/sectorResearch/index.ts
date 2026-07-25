import { pcbResearch } from "./pcb.ts";
import { humanoidResearch } from "./humanoid.ts";
import { aiComputingResearch } from "./ai-computing.ts";
import { hbmResearch } from "./hbm.ts";
import { cpoResearch } from "./cpo.ts";
import { smartDrivingResearch } from "./smart-driving.ts";
import { lowAltitudeResearch } from "./low-altitude.ts";
import { semiconductorResearch } from "./semiconductor.ts";
import { ssBatteryResearch } from "./solid-state-battery.ts";
import { innovativeDrugResearch } from "./innovative-drug/innovative-drug.ts";
import { fusionResearch } from "./fusion/fusion.ts";
import { defenseResearch } from "./defense/defense.ts";
import { businessSpaceResearch } from "./business-space/business-space.ts";
import { powerGridResearch } from "./power-grid/power-grid.ts";
import { aiApplicationResearch } from "./ai-application/ai-application.ts";
import { aiHardwareResearch } from "./ai-hardware/ai-hardware.ts";
import { energyStorageResearch } from "./energy-storage/energy-storage.ts";
import { dataElementResearch } from "./data-element/data-element.ts";
import { resourcesResearch } from "./resources/resources.ts";
import { aiPharmaResearch } from "./ai-pharma/ai-pharma.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import type { SectorResearchWorkspace } from "./types.ts";

export type { ContentBlock, ResearchTag, ResearchTagStatus, SectorResearchWorkspace, SourceRef } from "./types.ts";
export { getTagBySlug, resolveTagSlug } from "./types.ts";

/** 已启用「研究工作台」的板块注册表（未注册的仍走通用 SectorDetail） */
const WORKSPACES: Record<string, SectorResearchWorkspace> = {
  [pcbResearch.key]: pcbResearch,
  [humanoidResearch.key]: humanoidResearch,
  [aiComputingResearch.key]: aiComputingResearch,
  [hbmResearch.key]: hbmResearch,
  [semiconductorResearch.key]: semiconductorResearch,
  [ssBatteryResearch.key]: ssBatteryResearch,
  [cpoResearch.key]: cpoResearch,
  [smartDrivingResearch.key]: smartDrivingResearch,
  [lowAltitudeResearch.key]: lowAltitudeResearch,
  [innovativeDrugResearch.key]: innovativeDrugResearch,
  [fusionResearch.key]: fusionResearch,
  [defenseResearch.key]: defenseResearch,
  [businessSpaceResearch.key]: businessSpaceResearch,
  [powerGridResearch.key]: powerGridResearch,
  [aiApplicationResearch.key]: aiApplicationResearch,
  [aiHardwareResearch.key]: aiHardwareResearch,
  [energyStorageResearch.key]: energyStorageResearch,
  [dataElementResearch.key]: dataElementResearch,
  [resourcesResearch.key]: resourcesResearch,
  [aiPharmaResearch.key]: aiPharmaResearch,
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
