import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "全球光模块市场中，中国本土供应商在制造交付、供应链响应速度与成本控制上具备绝对竞争优势。中际旭创与新易盛领跑全球头部出货，天孚通信在无源组件环节拥有高粘性度。",
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING"],
  },
  {
    type: "bullets",
    items: [
      "模块出货领先：中际旭创、新易盛在 800G/1.6T 光模块订单中保持领先份额（公司口径）。",
      "上游器件支撑：天孚通信在 CPO 光引擎元件、光纤阵列领域实现配套（公司口径）。",
      "芯片自主化推进：源杰科技、光迅科技在大功率 CW 激光器及高速光芯片自研上取得积极进展（公司口径）。",
    ],
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING", "S-CPO-YUANJIE-FILING", "S-CPO-ACCELINK-FILING"],
  },
  {
    type: "table",
    caption: "光互联产业链核心供应商格局表",
    headers: ["环节", "关键支撑", "代表厂商", "事实/口径等级"],
    rows: [
      ["光模块整机", "800G/1.6T 光模块研发与制造", "中际旭创、新易盛、华工科技", "公司口径（年报披露）"],
      ["光无源器件", "FA光纤阵列、高精度透镜", "天孚通信", "公司口径（年报披露）"],
      ["激光器芯片", "100G EML与CW光源芯片", "源杰科技、光迅科技", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING", "S-CPO-YUANJIE-FILING", "S-CPO-ACCELINK-FILING", "S-CPO-HGTECH-FILING"],
  },
];
