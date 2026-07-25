import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI算力产业格局呈现海外芯片与架构主导、国内整机与组件快速演进的态势。浪潮信息、工业富联、紫光股份、中科曙光在服务器整机与交换机制造端具备很强的规模与工程落地能力。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-SUGON-FILING", "S-AICOMP-UNIS-FILING"],
  },
  {
    type: "bullets",
    items: [
      "服务器整机：浪潮信息在AI服务器出货量上保持前列，工业富联主导全球高端AI服务器代工制造（公司口径）。",
      "算力芯片：海光信息DCU生态兼容度高，寒武纪思元芯片在云端推理与特定智算项目中落地（公司口径）。",
      "网络基础设施：紫光股份（新华三）率先推出800G及CPO交换机（公司口径）。",
      "绿色液冷：中科曙光在浸没式液冷及冷板式液冷基础设施部署量上优势明显（公司口径）。",
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-HYGON-FILING", "S-AICOMP-CAMBRICON-FILING", "S-AICOMP-UNIS-FILING", "S-AICOMP-SUGON-FILING"],
  },
  {
    type: "table",
    caption: "AI 算力关键环节代表厂商能力对比",
    headers: ["环节", "核心能力/地位", "代表厂商", "公司口径/事实等级"],
    rows: [
      ["AI服务器", "高密度系统设计与量产工程能力", "浪潮信息、工业富联", "公司口径（年报披露）"],
      ["智算网络", "800G无损交换机与数据中心交换机", "紫光股份（新华三）", "公司口径（年报披露）"],
      ["相变液冷", "全浸没液冷技术与冷板CDU", "中科曙光", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-UNIS-FILING", "S-AICOMP-SUGON-FILING"],
  },
];
