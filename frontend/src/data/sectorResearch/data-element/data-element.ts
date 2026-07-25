import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { dataElementSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { attributionBlocks } from "./attribution.ts";
import { exchangeBlocks } from "./exchange.ts";
import { publicDataBlocks } from "./public-data.ts";
import { securityBlocks } from "./security.ts";
import { industryBlocks } from "./industry.ts";

export const dataElementResearch: SectorResearchWorkspace = {
  key: "data-element",
  label: "数据要素",
  fullName: "数据要素（Data Elements）",
  tagline: "数据确权、交易与流通基建",
  defaultTag: "overview",
  sources: dataElementSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "attribution", label: "确权", title: "确权", status: "draft", blocks: attributionBlocks },
    { slug: "exchange", label: "交易平台", title: "交易平台", status: "draft", blocks: exchangeBlocks },
    { slug: "public-data", label: "公共数据", title: "公共数据", status: "draft", blocks: publicDataBlocks },
    { slug: "security", label: "数据安全", title: "数据安全", status: "draft", blocks: securityBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(dataElementResearch);
