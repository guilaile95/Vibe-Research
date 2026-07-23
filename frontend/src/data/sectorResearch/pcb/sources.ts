import type { SourceRef } from "../types.ts";

/**
 * PCB 研究工作台共享来源注册表。
 * 仅登记本次实际读取的公司官网（公司口径）。
 * 标准/材料手册/研报/巨潮首页等未读正文，不进入正式 SourceRef。
 */
export const pcbSources: SourceRef[] = [
  // 景旺电子
  {
    id: "S-KINWONG-HLC",
    title: "景旺电子 - 高多层电路板产品页",
    org: "景旺电子（603228）",
    url: "https://www.kinwong.com/products-and-services/high-layer-count-pcbs/",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：最高80层、材料分级（M2~M9）、40:1厚径比、线宽/线距40/40μm、应用含AI服务器/交换机",
  },
  {
    id: "S-KINWONG-SLP",
    title: "景旺电子 - 类载板（SLP）产品页",
    org: "景旺电子（603228）",
    url: "https://www.kinwong.com/products-and-services/slp/",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：最高18层Anylayer、线宽/线距30/30μm、激光孔50μm、mSAP/amSAP工艺、应用含AI服务器/≥800G光模块/HPC",
  },
  {
    id: "S-KINWONG-COMPUTING",
    title: "景旺电子 - 计算市场（AI数据中心）",
    org: "景旺电子（603228）",
    url: "https://www.kinwong.com/markets/computing/",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：AI服务器PCB制造商定位、40层以上N+N结构、70+层高多层、9阶28层HDI、Skip-Via/POFV、背钻、高速板材料库",
  },
  {
    id: "S-KINWONG-TELECOM",
    title: "景旺电子 - 通信市场能力",
    org: "景旺电子（603228）",
    url: "https://www.kinwong.com/markets/telecom/",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：5.5G/6G基站、AAU/BBU、超高多层技术、高厚径比、N+N/M+N结构、高速材料混压、埋铜块",
  },

  // 生益科技
  {
    id: "S-SHENGYI-HIGHSPEED",
    title: "生益科技 - 高速产品系列",
    org: "生益科技（600183）",
    url: "https://www.syst.com.cn/cn/Product/list_255.aspx?parentid=238#pro",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：超低/低/中等介质损耗材料分类、Dk/Df/Tg/CTE参数范围、Synamic8GX 一般参数 Dk=3.62/Df=0.0016，10GHz 列 Dk@10GHz=3.66/Df@10GHz=0.0033；勿混用",
  },
  {
    id: "S-SHENGYI-RF",
    title: "生益科技 - 射频与微波材料",
    org: "生益科技（600183）",
    url: "https://www.syst.com.cn/cn/Product/list_255.aspx?parentid=250#pro",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：PTFE/热固性树脂/碳氢系列、mmWave77(Dk3.0/Df0.0010)、mmWaveG(Dk3.15/Df0.002)、毫米波雷达低损耗材料",
  },
  {
    id: "S-SHENGYI-IC",
    title: "生益科技 - IC封装产品",
    org: "生益科技（600183）",
    url: "https://www.syst.com.cn/cn/Product/list_255.aspx?parentid=248#pro",
    sourceType: "company_site",
    factLevel: "公司口径",
    note: "2026-07-24 实际打开读取；支撑：SI13U(CTE13/Tg245℃)、SI10US(CTE10/Tg280℃)等封装基板材料、Low CTE基板、高性能基板",
  },
];
