import type { SourceRef } from "../types.ts";

/**
 * 半导体国产替代研究工作台 — 共享来源注册表。
 * 保留已有年报 filing；补充官方政策页与公司官网/IR 公开页。
 * 未核验到真实 announcementId 的公告不伪造 id。
 */
export const semiconductorSources: SourceRef[] = [
  {
    id: "S-SEMI-NAURA-FILING",
    title: "北方华创 - 2023年年度报告",
    org: "北方华创（002371）",
    url: "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=002371&announcementId=1219908921",
    sourceType: "company_filing",
    factLevel: "公司口径",
    publishedAt: "2024-04-30",
    accessedAt: "2026-07-24",
    supports:
      "公司年报披露刻蚀、薄膜沉积、清洗、热处理等多类半导体核心设备的研发进展与出货量增长",
    note: "北方华创2023年年报",
  },
  {
    id: "S-SEMI-AMEC-FILING",
    title: "中微公司 - 2023年年度报告",
    org: "中微公司（688012）",
    url: "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688012&announcementId=1219329946",
    sourceType: "company_filing",
    factLevel: "公司口径",
    publishedAt: "2024-03-19",
    accessedAt: "2026-07-24",
    supports:
      "公司年报披露 CCP 刻蚀机与 MOCVD 设备在逻辑、存储及先进封装领域的高端工艺应用与出货量",
    note: "中微公司2023年年报",
  },
  {
    id: "S-SEMI-ANJI-FILING",
    title: "安集科技 - 2023年年度报告",
    org: "安集科技（688019）",
    url: "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688019&announcementId=1219623534",
    sourceType: "company_filing",
    factLevel: "公司口径",
    publishedAt: "2024-04-16",
    accessedAt: "2026-07-24",
    supports:
      "公司年报披露CMP抛光液、光刻胶去除剂及功能性湿电子化学品在14nm以下先进制程验证与导入进展",
    note: "安集科技2023年年报",
  },
  {
    id: "S-SEMI-SMIC-FILING",
    title: "中芯国际 - 2023年年度报告",
    org: "中芯国际（688981）",
    url: "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981&announcementId=1219447098",
    sourceType: "company_filing",
    factLevel: "公司口径",
    publishedAt: "2024-03-29",
    accessedAt: "2026-07-24",
    supports:
      "公司年报披露成熟制程晶圆代工产能利用率、资本开支计划与产能扩张路径，以及先进制程研发进展",
    note: "中芯国际2023年年报",
  },
  {
    id: "S-SEMI-MIIT-POLICY",
    title:
      "国务院《新时期促进集成电路产业和软件产业高质量发展的若干政策》（国发〔2020〕8号）",
    org: "国务院 / 工信部",
    url: "https://www.mee.gov.cn/zcwj/gwywj/202008/t20200806_792957.shtml",
    sourceType: "official",
    factLevel: "已确认事实",
    publishedAt: "2020-08-04",
    accessedAt: "2026-07-24",
    supports:
      "国务院发布集成电路产业高质量发展政策，明确财税、投融资、研发、进出口、人才、知识产权、市场应用、国际合作等八方面支持措施",
    note: "集成电路产业政策纲领性文件（生态环境部转载页）",
  },
  {
    id: "S-SEMI-GOV-POLICY",
    title:
      "中国政府网转载：新时期促进集成电路产业和软件产业高质量发展的若干政策",
    org: "中国政府网 / 国务院",
    url: "https://www.gov.cn/zhengce/content/2020-08/04/content_5532370.htm",
    sourceType: "official",
    factLevel: "已确认事实",
    publishedAt: "2020-08-04",
    accessedAt: "2026-07-25",
    supports:
      "与国发〔2020〕8号政策文本一致，可作为政策目标与支持方向的权威公开页；不提供分环节国产化率统计",
    note: "gov.cn 政策公开页，用于政策方向引用，不支撑具体百分比",
  },
  {
    id: "S-SEMI-NAURA-SITE",
    title: "北方华创官网 — 公司与半导体装备业务介绍",
    org: "北方华创（002371）",
    url: "https://www.naura.com/",
    sourceType: "company_site",
    factLevel: "公司口径",
    publishedAt: undefined,
    accessedAt: "2026-07-25",
    supports:
      "公司官网披露半导体工艺装备覆盖刻蚀、薄膜、清洗、热处理等前道核心工艺环节的产品与业务定位",
    note: "公司官网公开信息，用于设备品类与业务范围定性，不作市场份额断言",
  },
  {
    id: "S-SEMI-AMEC-SITE",
    title: "中微公司官网 — 刻蚀与薄膜设备产品介绍",
    org: "中微公司（688012）",
    url: "https://www.amec-inc.com/",
    sourceType: "company_site",
    factLevel: "公司口径",
    publishedAt: undefined,
    accessedAt: "2026-07-25",
    supports:
      "公司官网披露 CCP 等离子体刻蚀、MOCVD 等设备面向逻辑、存储与化合物半导体工艺的产品定位",
    note: "公司官网公开信息，用于设备品类与应用领域定性",
  },
  {
    id: "S-SEMI-SMIC-SITE",
    title: "中芯国际官网 — 晶圆代工与制造服务介绍",
    org: "中芯国际（688981）",
    url: "https://www.smics.com/",
    sourceType: "company_site",
    factLevel: "公司口径",
    publishedAt: undefined,
    accessedAt: "2026-07-25",
    supports:
      "公司官网披露晶圆代工服务、工艺平台与产能布局的公开介绍；不构成对先进节点量产时间表的官方确认",
    note: "公司官网公开信息，用于代工定位与工艺平台定性",
  },
];
