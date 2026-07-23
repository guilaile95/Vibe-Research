import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "人形机器人产业目前呈现出‘北美头部主机厂（如Tesla Optimus）引领需求 + 中国本土供应链快速跟进与送样验证’的格局。国内具备汽车零部件精密制造能力的厂商在执行器总成集成上优势明显。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "bullets",
    items: [
      "执行器总成：三花智控、拓普集团已建有专用试验线，并与海外主机厂开展深入样机合作（公司口径）。",
      "减速器环节：绿的谐波在谐波减速器领域占据本土首位，中大力德在精密行星减速器实现自研（公司口径）。",
      "空心杯电机：鸣志电器在空心杯电机及微型驱动控制领域具备国际竞争力（公司口径）。",
      "控制系统：汇川技术凭借工业伺服与变频控制积累，推进机器人控制器自研（公司口径）。",
    ],
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-ZHONGDA-FILING", "S-HUMANOID-MOONS-FILING", "S-HUMANOID-INOVANCE-FILING"],
  },
  {
    type: "table",
    caption: "人形机器人核心供应链参与度与技术成熟度表",
    headers: ["环节", "关键指标", "代表A股厂商", "技术成熟度", "事实/口径等级"],
    rows: [
      ["执行器总成", "旋转/直线一体化集成", "三花智控、拓普集团", "样机送样/专用产线建设", "公司口径（年报披露）"],
      ["精密减速器", "微型谐波/行星减速箱", "绿的谐波、中大力德", "批量出货/工程送样", "公司口径（年报披露）"],
      ["手部电机", "无齿槽空心杯电机", "鸣志电器、三花智控", "交样验证", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-MOONS-FILING"],
  },
];
