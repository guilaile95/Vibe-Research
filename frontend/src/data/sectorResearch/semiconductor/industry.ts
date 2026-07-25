import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "全球半导体供应链呈高度分工：美国在 EDA / IP 与部分核心设备领域领先，日本在材料与部分设备具优势，荷兰在高端光刻机领域关键，韩国与中国台湾在存储、先进逻辑代工与封装生态中占据重要位置。中国大陆则在成熟制程代工、部分设备与材料国产化上加速追赶。",
    sourceIds: ["S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY"],
  },
  {
    type: "bullets",
    items: [
      "刻蚀：北方华创、中微公司年报与官网披露面向逻辑与存储工艺的等离子体刻蚀设备进展。（公司口径）",
      "薄膜沉积：北方华创等披露 CVD / PVD / ALD 等薄膜设备产品线布局。（公司口径）",
      "材料：安集科技披露 CMP 抛光液等在先进制程的验证与导入。（公司口径）",
      "晶圆代工：中芯国际披露成熟制程产能、资本开支与工艺平台；先进节点公开信息需谨慎解读。（公司口径）",
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-SMIC-FILING",
      "S-SEMI-NAURA-SITE",
      "S-SEMI-AMEC-SITE",
      "S-SEMI-SMIC-SITE",
    ],
  },
  {
    type: "compareTable",
    caption: "国产化梯队示意（定性，非市场份额排名）",
    headers: ["梯队角色", "代表主体", "主要能力披露", "事实等级"],
    rows: [
      ["前道设备", "北方华创、中微公司", "刻蚀 / 薄膜 / 清洗等产品线", "公司口径"],
      ["关键材料", "安集科技等", "CMP 抛光液、湿电子化学品", "公司口径"],
      ["晶圆代工", "中芯国际等", "成熟制程代工与产能扩张", "公司口径"],
      ["政策与产业环境", "国务院集成电路政策", "财税、投融资、研发等支持方向", "已确认事实"],
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-SMIC-FILING",
      "S-SEMI-GOV-POLICY",
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "说明：本页不给出「某公司全球份额 X%」等无法由现有年报与政策页单独支撑的精确数字；梯队划分仅用于产业结构理解（内部分析）。",
    sourceIds: [],
  },
  {
    type: "risk",
    items: [
      "地缘政治与出口管制升级，可能同时冲击设备进口与海外市场拓展。",
      "高端人才与工艺 know-how 积累不足，拉长从「样机」到「稳定量产」的周期。",
      "成熟制程扩产过快时，可能出现阶段性供给过剩与价格压力。",
    ],
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY"],
  },
];
