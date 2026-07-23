/**
 * 板块 Tag 方案注册表 — 仅元数据（slug/label/title）。
 * 定义每个板块「将有哪些研究栏目」，不含研究正文（无段落、数字、结论）。
 * 供板块中心卡片文案（如 "6 个研究栏目"）和未来占位工作台页面使用。
 *
 * key 必须与 sectors.json 的 sectors[].key 严格一致；不一致时在模块加载期抛出。
 */

import sectorsData from "../sectors.json" with { type: "json" };

export type SectorTagPlan = {
  /** 稳定英文 slug，URL 段 */
  slug: string;
  /** Tag 导航短名（中文） */
  label: string;
  /** 内容区标题（中文） */
  title: string;
};

export type SectorTagRegistry = Record<string, SectorTagPlan[]>;

export const SECTOR_TAG_PLANS: SectorTagRegistry = {
  pcb: [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "technology", label: "原理与技术路线", title: "原理与技术路线" },
    { slug: "value", label: "价值量", title: "价值量" },
    { slug: "copper-midplane", label: "铜中板", title: "铜中板" },
    { slug: "industry", label: "产业格局", title: "产业格局" },
    { slug: "pricing-power", label: "定价权地图", title: "定价权地图" },
  ],
  "ai-computing": [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "architecture", label: "算力系统架构", title: "算力系统架构" },
    { slug: "value", label: "单机、单柜与集群价值量", title: "单机、单柜与集群价值量" },
    { slug: "scale-up", label: "Scale-up 网络与机柜架构", title: "Scale-up 网络与机柜架构" },
    {
      slug: "industry",
      label: "芯片、服务器、网络、散热产业格局",
      title: "芯片、服务器、网络、散热产业格局",
    },
    {
      slug: "pricing",
      label: "供给约束、定价权与资本开支信号",
      title: "供给约束、定价权与资本开支信号",
    },
  ],
  hbm: [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "dram-tsv", label: "DRAM 堆叠与 TSV 原理", title: "DRAM 堆叠与 TSV 原理" },
    { slug: "value", label: "单颗 GPU 和系统价值量", title: "单颗 GPU 和系统价值量" },
    {
      slug: "next-gen",
      label: "HBM4 / HBM4E 与下一代堆叠",
      title: "HBM4 / HBM4E 与下一代堆叠",
    },
    { slug: "industry", label: "DRAM、封装、设备与材料格局", title: "DRAM、封装、设备与材料格局" },
    { slug: "pricing", label: "产能分配、合约价与定价权", title: "产能分配、合约价与定价权" },
  ],
  cpo: [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "optics", label: "光模块、硅光和 CPO 原理", title: "光模块、硅光和 CPO 原理" },
    { slug: "value", label: "单端口和单集群价值量", title: "单端口和单集群价值量" },
    { slug: "next-gen", label: "1.6T / 3.2T / CPO", title: "1.6T / 3.2T / CPO" },
    { slug: "industry", label: "光芯片、器件、模块和代工格局", title: "光芯片、器件、模块和代工格局" },
    {
      slug: "risk",
      label: "供需、良率、价格与技术替代风险",
      title: "供需、良率、价格与技术替代风险",
    },
  ],
  semiconductor: [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "process",
      label: "晶圆制造流程与核心技术",
      title: "晶圆制造流程与核心技术",
    },
    { slug: "value", label: "设备和材料价值量", title: "设备和材料价值量" },
    {
      slug: "breakthrough",
      label: "先进制程、先进封装和关键设备突破",
      title: "先进制程、先进封装和关键设备突破",
    },
    { slug: "industry", label: "全球供应链与国产化梯队", title: "全球供应链与国产化梯队" },
    {
      slug: "pricing",
      label: "全球不可替代性与国产替代溢价",
      title: "全球不可替代性与国产替代溢价",
    },
  ],
  "ai-hardware": [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "architecture", label: "端侧 AI 设备架构", title: "端侧 AI 设备架构" },
    { slug: "value", label: "BOM 与单机价值量", title: "BOM 与单机价值量" },
    {
      slug: "devices",
      label: "AI 眼镜、AI 手机与边缘终端",
      title: "AI 眼镜、AI 手机与边缘终端",
    },
    { slug: "industry", label: "芯片、光学、整机与渠道格局", title: "芯片、光学、整机与渠道格局" },
    {
      slug: "pricing",
      label: "定价、换机周期和产品验证信号",
      title: "定价、换机周期和产品验证信号",
    },
  ],
  humanoid: [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "机械、电控和具身智能架构",
      title: "机械、电控和具身智能架构",
    },
    { slug: "value", label: "单机 BOM 与价值量", title: "单机 BOM 与价值量" },
    {
      slug: "actuators",
      label: "执行器、丝杠和灵巧手",
      title: "执行器、丝杠和灵巧手",
    },
    { slug: "industry", label: "零部件、整机与客户格局", title: "零部件、整机与客户格局" },
    {
      slug: "pricing",
      label: "降本能力、客户认证和量产信号",
      title: "降本能力、客户认证和量产信号",
    },
  ],
  "business-space": [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "systems", label: "火箭、卫星与地面系统", title: "火箭、卫星与地面系统" },
    { slug: "value", label: "发射和星座价值量", title: "发射和星座价值量" },
    {
      slug: "reuse",
      label: "可复用火箭与卫星批量制造",
      title: "可复用火箭与卫星批量制造",
    },
    {
      slug: "industry",
      label: "发射、卫星、载荷和地面设备格局",
      title: "发射、卫星、载荷和地面设备格局",
    },
    {
      slug: "pricing",
      label: "发射价格、产能、订单和政策信号",
      title: "发射价格、产能、订单和政策信号",
    },
  ],
  "low-altitude": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "飞行器、空域和运营体系",
      title: "飞行器、空域和运营体系",
    },
    { slug: "value", label: "eVTOL 与基础设施价值量", title: "eVTOL 与基础设施价值量" },
    {
      slug: "airworthiness",
      label: "适航、量产和商业运营",
      title: "适航、量产和商业运营",
    },
    {
      slug: "industry",
      label: "整机、零部件、空管和运营格局",
      title: "整机、零部件、空管和运营格局",
    },
    {
      slug: "pricing",
      label: "政策依赖、订单质量和盈利路径",
      title: "政策依赖、订单质量和盈利路径",
    },
  ],
  "smart-driving": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "感知、计算、规划与线控",
      title: "感知、计算、规划与线控",
    },
    { slug: "value", label: "单车价值量", title: "单车价值量" },
    {
      slug: "next-gen",
      label: "端到端、城市 NOA 与 Robotaxi",
      title: "端到端、城市 NOA 与 Robotaxi",
    },
    {
      slug: "industry",
      label: "芯片、算法、零部件与车企格局",
      title: "芯片、算法、零部件与车企格局",
    },
    {
      slug: "pricing",
      label: "软件收费、成本转嫁和监管风险",
      title: "软件收费、成本转嫁和监管风险",
    },
  ],
  defense: [
    { slug: "overview", label: "总览", title: "总览" },
    { slug: "architecture", label: "装备体系与产业链", title: "装备体系与产业链" },
    { slug: "value", label: "装备采购与价值量", title: "装备采购与价值量" },
    {
      slug: "modernization",
      label: "航空发动机、信息化和低成本消耗装备",
      title: "航空发动机、信息化和低成本消耗装备",
    },
    {
      slug: "industry",
      label: "总装、分系统和核心材料格局",
      title: "总装、分系统和核心材料格局",
    },
    {
      slug: "pricing",
      label: "订单节奏、价格机制和回款风险",
      title: "订单节奏、价格机制和回款风险",
    },
  ],
  "solid-state-battery": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "chemistry",
      label: "硫化物、氧化物和聚合物路线",
      title: "硫化物、氧化物和聚合物路线",
    },
    { slug: "value", label: "单机与材料价值量", title: "单机与材料价值量" },
    {
      slug: "manufacturing",
      label: "电解质、设备和量产工艺",
      title: "电解质、设备和量产工艺",
    },
    { slug: "industry", label: "材料、电池厂和设备格局", title: "材料、电池厂和设备格局" },
    {
      slug: "pricing",
      label: "良率、成本、专利与量产信号",
      title: "良率、成本、专利与量产信号",
    },
  ],
  "energy-storage": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "电化学与系统集成原理",
      title: "电化学与系统集成原理",
    },
    { slug: "value", label: "单站与系统价值量", title: "单站与系统价值量" },
    {
      slug: "next-gen",
      label: "长时储能和新型储能路线",
      title: "长时储能和新型储能路线",
    },
    {
      slug: "industry",
      label: "电芯、PCS、温控和集成商格局",
      title: "电芯、PCS、温控和集成商格局",
    },
    {
      slug: "pricing",
      label: "招标价格、利用率和收益机制",
      title: "招标价格、利用率和收益机制",
    },
  ],
  "power-grid": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "输电、变电与配电体系",
      title: "输电、变电与配电体系",
    },
    { slug: "value", label: "设备价值量与投资结构", title: "设备价值量与投资结构" },
    {
      slug: "uhv",
      label: "特高压、柔直和数字电网",
      title: "特高压、柔直和数字电网",
    },
    {
      slug: "industry",
      label: "变压器、组合电器和电力电子格局",
      title: "变压器、组合电器和电力电子格局",
    },
    {
      slug: "pricing",
      label: "招标价格、产能和电网资本开支",
      title: "招标价格、产能和电网资本开支",
    },
  ],
  fusion: [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "磁约束与惯性约束原理",
      title: "磁约束与惯性约束原理",
    },
    { slug: "value", label: "装置与核心设备价值量", title: "装置与核心设备价值量" },
    {
      slug: "components",
      label: "超导磁体、第一壁和加热系统",
      title: "超导磁体、第一壁和加热系统",
    },
    {
      slug: "industry",
      label: "国家装置、科研机构与供应链格局",
      title: "国家装置、科研机构与供应链格局",
    },
    {
      slug: "pricing",
      label: "技术里程碑、订单和商业化风险",
      title: "技术里程碑、订单和商业化风险",
    },
  ],
  resources: [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "geology",
      label: "资源形成、开采和提纯",
      title: "资源形成、开采和提纯",
    },
    { slug: "value", label: "下游需求与价值量", title: "下游需求与价值量" },
    {
      slug: "materials",
      label: "稀土、锗、镓、铟等关键资源",
      title: "稀土、锗、镓、铟等关键资源",
    },
    { slug: "industry", label: "储量、产能和加工地域格局", title: "储量、产能和加工地域格局" },
    {
      slug: "pricing",
      label: "出口政策、库存和资源定价权",
      title: "出口政策、库存和资源定价权",
    },
  ],
  "innovative-drug": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "pipeline",
      label: "靶点、临床和审批流程",
      title: "靶点、临床和审批流程",
    },
    { slug: "value", label: "单品种销售与授权价值", title: "单品种销售与授权价值" },
    {
      slug: "modalities",
      label: "ADC、双抗、GLP-1 与 License-out",
      title: "ADC、双抗、GLP-1 与 License-out",
    },
    { slug: "industry", label: "药企、Biotech 和 CXO 格局", title: "药企、Biotech 和 CXO 格局" },
    {
      slug: "pricing",
      label: "临床成功率、支付能力和定价权",
      title: "临床成功率、支付能力和定价权",
    },
  ],
  "ai-pharma": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "platforms",
      label: "生物技术平台与产业链",
      title: "生物技术平台与产业链",
    },
    { slug: "value", label: "产品和平台价值量", title: "产品和平台价值量" },
    {
      slug: "modalities",
      label: "细胞治疗、基因治疗和 AI 制药",
      title: "细胞治疗、基因治疗和 AI 制药",
    },
    { slug: "industry", label: "平台公司、制造和服务格局", title: "平台公司、制造和服务格局" },
    {
      slug: "pricing",
      label: "专利、监管、支付和商业化信号",
      title: "专利、监管、支付和商业化信号",
    },
  ],
  "ai-application": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "模型、Agent 和应用架构",
      title: "模型、Agent 和应用架构",
    },
    { slug: "value", label: "用户、收入和推理成本", title: "用户、收入和推理成本" },
    {
      slug: "vertical",
      label: "垂直 Agent 与企业软件",
      title: "垂直 Agent 与企业软件",
    },
    {
      slug: "industry",
      label: "模型厂、平台和应用公司格局",
      title: "模型厂、平台和应用公司格局",
    },
    {
      slug: "pricing",
      label: "付费率、留存、毛利率和渠道权",
      title: "付费率、留存、毛利率和渠道权",
    },
  ],
  "data-element": [
    { slug: "overview", label: "总览", title: "总览" },
    {
      slug: "architecture",
      label: "数据确权、授权和流通机制",
      title: "数据确权、授权和流通机制",
    },
    { slug: "value", label: "数据资产与交易价值", title: "数据资产与交易价值" },
    {
      slug: "authorization",
      label: "公共数据授权运营和数据空间",
      title: "公共数据授权运营和数据空间",
    },
    {
      slug: "industry",
      label: "数据交易所、服务商和平台格局",
      title: "数据交易所、服务商和平台格局",
    },
    {
      slug: "pricing",
      label: "收费机制、合规成本和政策信号",
      title: "收费机制、合规成本和政策信号",
    },
  ],
};

/** 取某板块的 Tag 方案；未注册则返回 undefined */
export function getSectorTagPlan(key: string): SectorTagPlan[] | undefined {
  return SECTOR_TAG_PLANS[key];
}

/** 取某板块的研究栏目数量；未注册则返回 0 */
export function getSectorTagCount(key: string): number {
  const plan = SECTOR_TAG_PLANS[key];
  return plan ? plan.length : 0;
}

/**
 * 校验所有 Tag 方案的 key 均存在于 sectors.json。
 * 任何 key 不一致即抛出，防止注册表与板块中心脱节。
 */
function validateAgainstSectorsJson(): void {
  const sectorKeys = new Set(sectorsData.sectors.map((s) => s.key));
  for (const key of Object.keys(SECTOR_TAG_PLANS)) {
    if (!sectorKeys.has(key)) {
      throw new Error(`sectorTagPlans: key "${key}" not found in sectors.json`);
    }
  }
}

validateAgainstSectorsJson();
