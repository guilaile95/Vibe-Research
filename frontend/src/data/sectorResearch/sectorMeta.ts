import type { ResearchTagStatus } from './types.ts';

export interface SectorMeta {
  key: string; label: string; fullName: string; tagline: string; defaultTag: string;
  tags: { slug: string; label: string; title: string; status: ResearchTagStatus }[];
}

export function getSectorMeta(key: string | undefined): SectorMeta | undefined {
  if (!key) return undefined;
  return SECTOR_META[key];
}

export function hasSectorResearchWorkspace(key: string | undefined): boolean {
  return getSectorMeta(key) !== undefined;
}

export function listSectorResearchKeys(): string[] {
  return Object.keys(SECTOR_META);
}

/** 供卡片文案：研究栏目数量（不含正文，仅骨架）。 */
export function getResearchTagCount(key: string | undefined): number | undefined {
  const meta = getSectorMeta(key);
  return meta ? meta.tags.length : undefined;
}

export function getDefaultResearchPath(key: string): string | undefined {
  const meta = getSectorMeta(key);
  if (!meta) return undefined;
  return `/sectors/${meta.key}/${meta.defaultTag}`;
}

export interface ResolvedTagMeta {
  workspaceKey: string;
  tagSlug: string;
  redirected: boolean;
}

/** 同步版 resolveOrFallback：仅依赖元数据（slug + defaultTag），不加载正文块。 */
export function resolveSectorTagMeta(
  key: string,
  slug: string | undefined,
): ResolvedTagMeta | null {
  const meta = getSectorMeta(key);
  if (!meta) return null;
  const resolved =
    slug && meta.tags.some((t) => t.slug === slug) ? slug : meta.defaultTag;
  return {
    workspaceKey: meta.key,
    tagSlug: resolved,
    redirected: resolved !== slug,
  };
}

export const SECTOR_META: Record<string, SectorMeta> = {
  "pcb": {
    key: "pcb", label: "PCB", fullName: "PCB（印制电路板）",
    tagline: "AI 服务器的骨架公路——承载加速卡、内存、交换芯片、电源与高速互连", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "technology", label: "technology", title: "technology", status: "placeholder" }, { slug: "value", label: "value", title: "value", status: "placeholder" }, { slug: "copper-midplane", label: "copper-midplane", title: "copper-midplane", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing-power", label: "pricing-power", title: "pricing-power", status: "placeholder" }],
  },
  "humanoid": {
    key: "humanoid", label: "人形机器人", fullName: "人形机器人（Humanoid Robotics）",
    tagline: "具身智能的最佳物理载体——融合AI大模型、精密传动、执行器与传感器", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "architecture", label: "architecture", title: "architecture", status: "placeholder" }, { slug: "value", label: "value", title: "value", status: "placeholder" }, { slug: "actuators", label: "actuators", title: "actuators", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "ai-computing": {
    key: "ai-computing", label: "AI算力", fullName: "AI算力（AI Computing Infrastructure）",
    tagline: "大模型时代的物理底座——芯片、服务器、高速网络与绿色液冷基础设施", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "architecture", label: "算力系统架构", title: "算力系统架构", status: "placeholder" }, { slug: "value", label: "单机、单柜与集群价值量", title: "单机、单柜与集群价值量", status: "placeholder" }, { slug: "scale-up", label: "Scale-up 网络与机柜架构", title: "Scale-up 网络与机柜架构", status: "placeholder" }, { slug: "industry", label: "DRAM、封装、设备与材料格局", title: "DRAM、封装、设备与材料格局", status: "placeholder" }, { slug: "pricing", label: "产能分配、合约价与定价权", title: "产能分配、合约价与定价权", status: "placeholder" }],
  },
  "hbm": {
    key: "hbm", label: "HBM", fullName: "HBM（高带宽内存）",
    tagline: "突破‘内存墙’的显存利器——TSV硅通孔、垂直堆叠与先进封装", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "dram-tsv", label: "dram-tsv", title: "dram-tsv", status: "placeholder" }, { slug: "value", label: "value", title: "value", status: "placeholder" }, { slug: "next-gen", label: "next-gen", title: "next-gen", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "cpo": {
    key: "cpo", label: "光互联", fullName: "光互联与 CPO（Optical Interconnects & CPO）",
    tagline: "AI算力集群的高速血脉——800G/1.6T 光模块、硅光集成与 CPO 共封装", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "optics", label: "optics", title: "optics", status: "placeholder" }, { slug: "value", label: "value", title: "value", status: "placeholder" }, { slug: "next-gen", label: "next-gen", title: "next-gen", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "risk", label: "risk", title: "risk", status: "placeholder" }],
  },
  "smart-driving": {
    key: "smart-driving", label: "智能驾驶", fullName: "智能驾驶（Smart Driving）",
    tagline: "感知→计算→执行的智能化闭环——融合传感器、域控、线控与 AI 算法的汽车产业主线", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "architecture", label: "装备体系与产业链", title: "装备体系与产业链", status: "placeholder" }, { slug: "value", label: "单车价值量", title: "单车价值量", status: "placeholder" }, { slug: "next-gen", label: "next-gen", title: "next-gen", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "low-altitude": {
    key: "low-altitude", label: "低空经济", fullName: "低空经济（Low-Altitude Economy）",
    tagline: "eVTOL、无人机与低空运营——政策驱动走向适航落地的万亿级赛道", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "architecture", label: "architecture", title: "architecture", status: "placeholder" }, { slug: "value", label: "eVTOL 与基础设施价值量", title: "eVTOL 与基础设施价值量", status: "placeholder" }, { slug: "airworthiness", label: "airworthiness", title: "airworthiness", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "semiconductor": {
    key: "semiconductor", label: "半导体国产替代", fullName: "半导体产业链：设备、材料与国产替代",
    tagline: "设备、材料、EDA、制造的自主链条", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "process", label: "process", title: "process", status: "placeholder" }, { slug: "value", label: "value", title: "value", status: "placeholder" }, { slug: "breakthrough", label: "breakthrough", title: "breakthrough", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "solid-state-battery": {
    key: "solid-state-battery", label: "固态电池", fullName: "固态电池（Solid-State Battery）",
    tagline: "下一代动力电池的核心路线——安全性、能量密度与产业链重构", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "chemistry", label: "chemistry", title: "chemistry", status: "placeholder" }, { slug: "value", label: "单机与材料价值量", title: "单机与材料价值量", status: "placeholder" }, { slug: "manufacturing", label: "manufacturing", title: "manufacturing", status: "placeholder" }, { slug: "industry", label: "材料、电池厂和设备格局", title: "材料、电池厂和设备格局", status: "placeholder" }, { slug: "pricing", label: "pricing", title: "pricing", status: "placeholder" }],
  },
  "innovative-drug": {
    key: "innovative-drug", label: "创新药", fullName: "创新药（Innovative Drug）",
    tagline: "靶点、临床、CXO 与出海", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "target", label: "target", title: "target", status: "placeholder" }, { slug: "clinical", label: "clinical", title: "clinical", status: "placeholder" }, { slug: "cxo", label: "cxo", title: "cxo", status: "placeholder" }, { slug: "chuhai", label: "chuhai", title: "chuhai", status: "placeholder" }, { slug: "industry", label: "药企、Biotech 和 CXO 格局", title: "药企、Biotech 和 CXO 格局", status: "placeholder" }],
  },
  "fusion": {
    key: "fusion", label: "可控核聚变", fullName: "可控核聚变（Magnetic Confinement Fusion）",
    tagline: "磁约束、超导与第一壁材料", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "magnetic", label: "magnetic", title: "magnetic", status: "placeholder" }, { slug: "superconducting", label: "superconducting", title: "superconducting", status: "placeholder" }, { slug: "firstwall", label: "firstwall", title: "firstwall", status: "placeholder" }, { slug: "plasma", label: "plasma", title: "plasma", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "defense": {
    key: "defense", label: "军工", fullName: "军工（Defense Industry）",
    tagline: "航空、航天、船舶与信息化", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "aviation", label: "aviation", title: "aviation", status: "placeholder" }, { slug: "aerospace", label: "aerospace", title: "aerospace", status: "placeholder" }, { slug: "naval", label: "naval", title: "naval", status: "placeholder" }, { slug: "informatization", label: "informatization", title: "informatization", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "business-space": {
    key: "business-space", label: "商业航天", fullName: "商业航天（Commercial Space）",
    tagline: "火箭、卫星制造与卫星互联网", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "rocket", label: "rocket", title: "rocket", status: "placeholder" }, { slug: "satellite", label: "satellite", title: "satellite", status: "placeholder" }, { slug: "internet", label: "internet", title: "internet", status: "placeholder" }, { slug: "ttc", label: "ttc", title: "ttc", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "power-grid": {
    key: "power-grid", label: "电网与特高压", fullName: "电网与特高压（Power Grid & UHV）",
    tagline: "输配电设备与新型电力系统", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "uhv", label: "uhv", title: "uhv", status: "placeholder" }, { slug: "transmission", label: "transmission", title: "transmission", status: "placeholder" }, { slug: "new-energy", label: "new-energy", title: "new-energy", status: "placeholder" }, { slug: "intelligence", label: "intelligence", title: "intelligence", status: "placeholder" }, { slug: "industry", label: "储量、产能和加工地域格局", title: "储量、产能和加工地域格局", status: "placeholder" }],
  },
  "ai-application": {
    key: "ai-application", label: "AI 应用", fullName: "AI 应用（AI Application & Agent）",
    tagline: "大模型落地的应用与 Agent", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "office-agent", label: "office-agent", title: "office-agent", status: "placeholder" }, { slug: "coding-agent", label: "coding-agent", title: "coding-agent", status: "placeholder" }, { slug: "industry-ai", label: "industry-ai", title: "industry-ai", status: "placeholder" }, { slug: "multimodal", label: "multimodal", title: "multimodal", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "ai-hardware": {
    key: "ai-hardware", label: "AI 硬件", fullName: "AI 硬件（AI Glasses & Edge Devices）",
    tagline: "端侧、AI 眼镜与消费终端", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "ai-glasses", label: "ai-glasses", title: "ai-glasses", status: "placeholder" }, { slug: "edge-chip", label: "edge-chip", title: "edge-chip", status: "placeholder" }, { slug: "wearable", label: "wearable", title: "wearable", status: "placeholder" }, { slug: "smart-home", label: "smart-home", title: "smart-home", status: "placeholder" }, { slug: "industry", label: "芯片、光学、整机与渠道格局", title: "芯片、光学、整机与渠道格局", status: "placeholder" }],
  },
  "energy-storage": {
    key: "energy-storage", label: "储能", fullName: "储能（Energy Storage）",
    tagline: "电化学储能与电网侧调峰", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "electrochemical", label: "electrochemical", title: "electrochemical", status: "placeholder" }, { slug: "integration", label: "integration", title: "integration", status: "placeholder" }, { slug: "pcs", label: "pcs", title: "pcs", status: "placeholder" }, { slug: "grid-side", label: "grid-side", title: "grid-side", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "data-element": {
    key: "data-element", label: "数据要素", fullName: "数据要素（Data Elements）",
    tagline: "数据确权、交易与流通基建", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "attribution", label: "attribution", title: "attribution", status: "placeholder" }, { slug: "exchange", label: "exchange", title: "exchange", status: "placeholder" }, { slug: "public-data", label: "public-data", title: "public-data", status: "placeholder" }, { slug: "security", label: "security", title: "security", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "resources": {
    key: "resources", label: "资源卡口", fullName: "资源卡口（Critical Resources）",
    tagline: "稀土、锗、铟等被卡的关键资源", defaultTag: "overview",
    tags: [{ slug: "overview", label: "overview", title: "overview", status: "placeholder" }, { slug: "rare-earth", label: "rare-earth", title: "rare-earth", status: "placeholder" }, { slug: "germanium", label: "germanium", title: "germanium", status: "placeholder" }, { slug: "lithium", label: "lithium", title: "lithium", status: "placeholder" }, { slug: "tungsten", label: "tungsten", title: "tungsten", status: "placeholder" }, { slug: "industry", label: "industry", title: "industry", status: "placeholder" }],
  },
  "ai-pharma": {
    key: "ai-pharma", label: "生物医药/AI制药", fullName: "生物医药/AI制药（Biotech & AI Pharma）",
    tagline: "创新药、AI 制药与生物技术", defaultTag: "overview",
    tags: [{ slug: "overview", label: "总览", title: "总览", status: "placeholder" }, { slug: "ai-drug", label: "ai-drug", title: "ai-drug", status: "placeholder" }, { slug: "gene-therapy", label: "gene-therapy", title: "gene-therapy", status: "placeholder" }, { slug: "cxo", label: "cxo", title: "cxo", status: "placeholder" }, { slug: "devices", label: "devices", title: "devices", status: "placeholder" }, { slug: "industry", label: "平台公司、制造和服务格局", title: "平台公司、制造和服务格局", status: "placeholder" }],
  },
};
