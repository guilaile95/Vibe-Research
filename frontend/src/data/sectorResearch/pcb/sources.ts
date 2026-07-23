import type { SourceRef } from "../types.ts";

/**
 * PCB 研究工作台共享来源注册表。
 * 仅登记本次实际读取的公司官网（公司口径）。
 * 标准/材料手册/研报/巨潮首页等未读正文，不进入正式 SourceRef。
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
];
