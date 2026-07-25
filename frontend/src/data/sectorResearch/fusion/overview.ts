import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "可控核聚变被视为人类终极能源技术。其核心科学目标是实现等离子体的持续、稳定燃烧（Lawson判据），使聚变功率Q值>1（科学增益）并最终达到Q>10（工程增益）以支撑商用发电。当前全球领先实验装置已实现等离子体温度>1亿摄氏度、长脉冲H模运行等里程碑。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-IAEA"],
  },
  {
    type: "paragraph",
    text: "磁约束（托卡马克）是当前核聚变研究的主流技术路线，其工程实现依赖三大核心技术：超导磁体（强磁场约束等离子体）、第一壁/偏滤器（承受极端热流与中子辐加热）、等离子体控制（加热与约束）。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-CFETR", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-ANTAI-2023"],
  },
  {
    type: "bullets",
    items: [
      "国际标杆：ITER（法国卡达拉舍，35国合作）计划2035年首次等离子体放电，Q>10。",
      "中国主力装置：EAST（合肥，全超导托卡马克，已实现403秒长脉冲H模）、CFETR（工程设计阶段，连接ITER与商用堆的桥梁）。",
      "国内上市公司布局：联创光电（高温超导）、西部超导（低温/高温超导）、安泰科技（第一壁材料）、国光电气（等离子体设备）、中国核建（工程配套）。",
      "核心瓶颈：超导磁体（Nb3Sn/REBCO）、第一壁材料（钨/钍基/ODS钢）、氚增殖包层与氚自持。",
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR", "S-FUSION-LIANCHUANG-2023", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-ANTAI-2023", "S-FUSION-GUOGUANG-2023", "S-FUSION-CNNC-2023"],
  },
  {
    type: "table",
    caption: "全球主要托卡马克装置与国内布局",
    headers: ["装置", "国家/机构", "类型", "主要里程碑/目标", "事实/口径等级"],
    rows: [
      ["ITER", "35国合作（EU/US/CN/JP/K/RU/IN）", "大型超导托卡马克", "2035首次等离子体放电，Q>10", "已确认事实"],
      ["EAST", "中科院等离子体所（合肥）", "全超导托卡马克", "403秒长脉冲H模，>1亿℃", "已确认事实"],
      ["HL-2A / HL-2M", "核工业西南物理研究院（成都）", "常规/改进托卡马克", "先进等离子体约束与加热实验", "已确认事实"],
      ["CFETR", "中国核聚变工程实验堆", "下一代工程实验堆", "连接ITER与商用堆，GW级聚变功率目标", "已确认事实"],
      ["SPARC (CFS)", "MIT/CFS (美国)", "高温超导紧凑型", "预期2025-2026 Q>1", "公开信息"],
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR", "S-FUSION-IAEA"],
  },
];
