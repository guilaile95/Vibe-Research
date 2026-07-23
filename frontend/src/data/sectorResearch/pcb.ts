import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";

const PLACEHOLDER =
  "该栏目框架已建立，等待下一步研究内容填充。正式结论、数字与产业判断将在后续步骤按 Tag 逐步写入；当前页面不展示研究底稿正文。";

/**
 * PCB（印制电路板）研究工作台 — 第 2 步仅框架 + 六 Tag 占位。
 * 正式正文由第 3—8 步分别填充，勿在此文件提前写入完整研究结论。
 */
export const pcbResearch: SectorResearchWorkspace = {
  key: "pcb",
  label: "PCB",
  fullName: "PCB（印制电路板）",
  tagline: "AI 服务器的骨架公路——承载加速卡、内存、交换芯片、电源与高速互连",
  defaultTag: "overview",
  sources: [],
  tags: [
    {
      slug: "overview",
      label: "总览",
      title: "总览",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
    {
      slug: "technology",
      label: "原理与技术路线",
      title: "原理与技术路线",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
    {
      slug: "value",
      label: "价值量",
      title: "价值量",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
    {
      slug: "copper-midplane",
      label: "铜中板",
      title: "铜中板",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
    {
      slug: "industry",
      label: "产业格局",
      title: "产业格局",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
    {
      slug: "pricing-power",
      label: "定价权地图",
      title: "定价权地图",
      status: "placeholder",
      blocks: [{ type: "placeholder", text: PLACEHOLDER }],
    },
  ],
};

assertWorkspaceInvariants(pcbResearch);
