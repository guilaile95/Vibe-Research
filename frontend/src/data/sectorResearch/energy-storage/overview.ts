import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层目标：发改能源规〔2022〕1011号明确到2025年新型储能步入规模化发展阶段，到2030年全面市场化发展。CNESA统计2024年中国新型储能累计装机超50GW，2025年预计新增超30GW。",
    sourceIds: ["S-ESA-NEA-NE-PLAN", "S-ESA-CNESA-DATA"],
  },
  {
    type: "paragraph",
    text: "储能板块涵盖电池电芯（宁德时代/比亚迪）、储能变流器PCS（阳光电源/科士达/盛弘）、储能系统集成与电化学储能解决方案。在新能源强制配储、电网侧调峰与海外户储三重驱动下，储能行业保持高速增长。",
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-CNESA-DATA"],
  },
  {
    type: "bullets",
    items: [
      "电化学储能：以锂离子电池为主流，钠离子、液流电池等新技术逐步导入，2小时-4小时储能时长是主流配置。",
      "储能变流器(PCS)：连接电池系统与电网，实现交直流转换与充放电控制，是储能系统核心电力电子设备。",
      "系统集成：涵盖电池簇、BMS、EMS、热管理与消防系统，向大容量、高安全、长寿命方向升级。",
      "应用场景：发电侧（新能源配储）、电网侧（独立储能/共享储能）、用户侧（工商业储能/户储）三大类。",
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
  {
    type: "table",
    caption: "储能板块核心子领域与代表厂商",
    headers: ["子领域", "核心产品", "技术门槛", "代表A股厂商"],
    rows: [
      ["储能电池", "电芯/模组/Pack", "一致性、循环寿命、成本控制", "宁德时代、比亚迪、亿纬锂能"],
      ["储能PCS", "储能变流器", "转换效率、电网适应性", "阳光电源、科士达、盛弘股份"],
      ["储能系统集成", "集装箱储能系统", "系统集成能力、安全认证", "阳光电源、比亚迪、科华数据"],
      ["BMS/EMS", "电池管理/能量管理", "算法精度、均衡控制", "宁德时代、阳光电源、科士达"],
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
];
