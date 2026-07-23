import type { ContentBlock } from "../types.ts";

export const actuatorsBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "传动部件物理极限：旋转关节需承受大扭矩冲击与频繁倒转，直线关节需解决反向驱动与高疲劳寿命问题。",
    sourceIds: ["S-HUMANOID-GREENHARMONIC-FILING"],
  },
  {
    type: "paragraph",
    text: "执行器与丝杠是人形机器人实现高精度、高负载运动的核心物理部件。丝杠技术路线（行星滚柱丝杠 vs 梯形/滚珠丝杠）与减速器路线（谐波 vs 行星 vs RV）决定了关节的物理上限。",
    sourceIds: ["S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-ZHONGDA-FILING", "S-HUMANOID-MOONS-FILING"],
  },
  {
    type: "compareTable",
    caption: "三大核心传动零部件技术路线对比表",
    headers: ["传动部件", "核心优势", "主要局限", "应用场景", "国内突破瓶颈"],
    rows: [
      ["谐波减速器", "体积小、重量轻、传动比大(50-160)", "柔轮易疲劳失效、刚度较低", "旋转关节（肩/肘/手腕）", "高交叉滚子轴承与材料抗疲劳寿命"],
      ["行星滚柱丝杠", "承载能力大、寿命长、耐冲击", "加工极为复杂、成本高昂", "直线执行器（腿部/膝盖伸缩）", "硬旋风铣削设备与精密滚柱加工"],
      ["空心杯电机", "无齿槽效应、响应快(时间常数<10ms)", "功率密度受限、散热较难", "灵巧手指关节驱动", "微型绕线机与高磁能积永磁体装配"],
    ],
    sourceIds: ["S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-MOONS-FILING", "S-HUMANOID-ZHONGDA-FILING"],
  },
];
