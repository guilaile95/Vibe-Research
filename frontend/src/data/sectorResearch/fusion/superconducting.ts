import type { ContentBlock } from "../types.ts";

export const superconductingBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "超导磁体是托卡马克装置的核心使能技术。根据工作温度与材料类型，分为低温超导（LTS：NbTi、Nb3Sn，4.2K）与高温超导（HTS：REBCO、Bi-2212/Bi-2223，20-77K）。REBCO（稀土钡铜氧）带材因高临界磁场与电流密度，正成为下一代聚变磁体的关键技术路径。",
    sourceIds: ["S-FUSION-WESTSUPERCON-2023", "S-FUSION-LIANCHUANG-2023", "S-FUSION-ITER"],
  },
  {
    type: "paragraph",
    text: "ITER采用Nb3Sn（环向场/极向场线圈）与NbTi（中心螺线管）超导材料，需要约700吨Nb3Sn与约250吨NbTi超导线材。中国西部超导是国内唯一实现Nb3Sn超导线材量产并供货ITER的企业；联创光电布局高温超导在核聚变/磁储能/磁牵引等方向的工程化应用。",
    sourceIds: ["S-FUSION-WESTSUPERCON-2023", "S-FUSION-LIANCHUANG-2023", "S-FUSION-ITER"],
  },
  {
    type: "table",
    caption: "超导材料分类与在核聚变中的应用",
    headers: ["材料", "临界温度Tc", "临界磁场", "主要应用", "代表公司", "事实/口径等级"],
    rows: [
      ["NbTi", "9.2K", "~15T（4.2K）", "MRI、中小型加速器", "西部超导、Oxford", "已确认事实"],
      ["Nb3Sn", "18K", "~30T（4.2K）", "ITER TF/PF/CS线圈", "西部超导", "已确认事实"],
      ["Bi-2212", "85K", ">45T（4.2K）", "高磁场磁体", "牛津仪器", "已确认事实"],
      ["REBCO（二代高温超导）", "~90K", ">30T（20K）", "CFETR/SPARC/高温超导磁体", "联创光电、上海超导", "公司口径"],
    ],
    sourceIds: ["S-FUSION-WESTSUPERCON-2023", "S-FUSION-LIANCHUANG-2023", "S-FUSION-ITER"],
  },
  {
    type: "bullets",
    items: [
      "ITER国内采购包：中国承担ITER超导线圈、PF线圈、TF线圈等多个采购包，西部超导与安泰科技是国内核心供应商。",
      "高温超导工程化：联创光电布局高温超导感应加热器、磁储能与核聚变磁体工程化，已实现工业级高温超导样机示范。",
      "下一代磁体：CFS（Commonwealth Fusion Systems）采用REBCO带材建造SPARC装置（20T级磁场），计划2025-2026实现Q>1。",
    ],
    sourceIds: ["S-FUSION-ITER-CHINA", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-LIANCHUANG-2023"],
  },
];
