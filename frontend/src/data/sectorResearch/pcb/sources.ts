import type { SourceRef } from "../types.ts";

/**
 * PCB 研究工作台共享来源注册表。
 * 所有 per-tag 内容文件引用这里的 source id。
 *
 * 公司代码经 a-stock-data 实际验证：
 *   沪电股份 002463 / 深南电路 002916 / 景旺电子 603228 /
 *   胜宏科技 300476 / 生益科技 600183 / 方正科技 600601。
 * 欣興電子（UNIMICRON，台湾）与 AT&S（奥地利）为非 A 股，仅作产业来源。
 */
export const pcbSources: SourceRef[] = [
  {
    id: "S-KINWONG",
    title: "景旺电子官网（产品/市场/技术）",
    org: "景旺电子（603228）",
    url: "https://www.kinwong.com",
    sourceType: "company_site",
    factLevel: "公司口径",
  },
  {
    id: "S-UNIMICRON",
    title: "欣興電子官网（产品/技术/研发）",
    org: "欣興電子（UNIMICRON，台湾）",
    url: "https://www.unimicron.com",
    sourceType: "company_site",
    factLevel: "公司口径",
  },
  {
    id: "S-SHENGYI",
    title: "生益科技官网（产品/研发/标准）",
    org: "生益科技（600183）",
    url: "https://www.syst.com.cn",
    sourceType: "company_site",
    factLevel: "公司口径",
  },
  {
    id: "S-IPC-6012E",
    title: "IPC-6012E 刚性印制板鉴定与性能规范",
    org: "IPC International",
    url: "https://www.ipc.org/ipc-6012e-qualification-and-performance-specification-rigid-printed-boards",
    sourceType: "standard",
    factLevel: "已确认事实",
  },
  {
    id: "S-IPC-4101",
    title: "IPC-4101 刚性及多层印制板用基础材料规范",
    org: "IPC International",
    url: "https://www.ipc.org/ipc-4101c-specification-base-materials-rigid-and-multilayer",
    sourceType: "standard",
    factLevel: "已确认事实",
  },
  {
    id: "S-PANASONIC-MEGTRON",
    title: "Panasonic Megtron 6/7 数据手册",
    org: "Panasonic Industrial Devices",
    url: "https://www.panasonic.com/industrial/megtron",
    sourceType: "whitepaper",
    factLevel: "公司口径",
  },
  {
    id: "S-ISOLA",
    title: "Isola I-Speed / I-Tera / Astra 数据手册",
    org: "Isola Group",
    url: "https://isolagroup.com/products",
    sourceType: "whitepaper",
    factLevel: "公司口径",
  },
  {
    id: "S-ROGERS",
    title: "Rogers / Arlon 高频层压板数据手册",
    org: "Rogers Corporation",
    url: "https://rogerscorp.com/advanced-connectivity-solutions",
    sourceType: "whitepaper",
    factLevel: "公司口径",
  },
  {
    id: "S-ITEQ",
    title: "I-Tech IT-968 / IT-970 数据手册",
    org: "I-Tech Corp.",
    url: "https://www.i-tech.com.tw",
    sourceType: "whitepaper",
    factLevel: "公司口径",
  },
  {
    id: "S-PRISMARK",
    title: "Prismark Partners AI 服务器 PCB 市场公开摘要",
    org: "Prismark Partners",
    url: "https://www.prismarkpartners.com",
    sourceType: "report_summary",
    factLevel: "机构预测",
  },
  {
    id: "S-TRENDFORCE",
    title: "TrendForce AI 服务器 / HPC 公开新闻稿",
    org: "TrendForce",
    url: "https://www.trendforce.com/presscenter/news/",
    sourceType: "report_summary",
    factLevel: "机构预测",
  },
  {
    id: "S-HUATONG-002463",
    title: "沪电股份（002463）年报 / 中报 / 投资者关系",
    org: "沪电股份",
    url: "http://www.cninfo.com.cn",
    sourceType: "company_filing",
    factLevel: "公司口径",
  },
  {
    id: "S-SHENNAN-002916",
    title: "深南电路（002916）年报 / 中报",
    org: "深南电路",
    url: "http://www.cninfo.com.cn",
    sourceType: "company_filing",
    factLevel: "公司口径",
  },
  {
    id: "S-SHENGHONG-300476",
    title: "胜宏科技（300476）年报 / 中报",
    org: "胜宏科技",
    url: "http://www.cninfo.com.cn",
    sourceType: "company_filing",
    factLevel: "公司口径",
  },
  {
    id: "S-BROKERAGE-AI-PCB",
    title: "券商电子行业研报（AI PCB 主题）",
    org: "多家券商",
    sourceType: "report_summary",
    factLevel: "机构预测",
  },
];
