import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "成本结构特征：人形机器人单机 BOM 成本在早期量产阶段占比极高，随着规模效应显现，执行器与滚柱丝杠等核心传动部件具备 50% 以上降本弹性。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING"],
  },
  {
    type: "paragraph",
    text: "在人形机器人初期小批量（如万台级）阶段，硬件BOM成本占整机成本的80%以上。其中执行器（旋转+直线）与灵巧手构成了BOM价值量的核心。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "table",
    caption: "人形机器人单机 BOM 结构与价值量分布表",
    headers: ["部件名称", "单机使用数量", "价值量占比区间", "主要成本驱动因素", "代表供应商"],
    rows: [
      ["旋转执行器", "12 ~ 14 个", "30% ~ 35%", "谐波减速器柔轮加工、无框电机绕线", "三花智控、拓普集团、绿的谐波"],
      ["直线执行器", "8 ~ 14 个", "25% ~ 30%", "行星滚柱丝杠磨削、淬火与装配", "三花智控、拓普集团、中大力德"],
      ["双手灵巧手", "2 套（10-12电机）", "10% ~ 15%", "空心杯电机微型化、微型齿轮箱", "鸣志电器、三花智控"],
      ["传感与主控", "IMU+力传感器+SoC", "10% ~ 15%", "六维力传感器应变片贴片与解算芯片", "汇川技术（主控）"],
      ["结构件与电池", "外壳+骨架+动力电池", "10% ~ 15%", "碳纤维/铝镁合金轻量化与高能量密度电池", "拓普集团（结构件）"],
    ],
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-MOONS-FILING"],
  },
];
