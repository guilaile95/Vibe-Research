import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "成本结构特征（分析推断）：在人形机器人早期小批量样机阶段，硬件 BOM 占整机成本比例极高。随着制造规模扩大与自动化产线建立（拓普/三花等披露规划），关节执行器与精密传动部件具备较大的降本空间。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "paragraph",
    text: "人形机器人硬件结构中，关节执行器（旋转执行器与直线执行器）以及手部灵巧手驱动系统占据了硬件总成本的主要份额。各模块价值量取决于零部件加工精度与机电一体化集成度。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "table",
    caption: "人形机器人单机 BOM 结构与环节分布表（分析推断）",
    headers: ["部件名称", "主要构成", "成本驱动与瓶颈", "代表 A 股厂商", "供应链映射状态"],
    rows: [
      ["旋转执行器", "无框电机 + 谐波/RV减速器 + 双编码器", "谐波减速器柔轮加工、无框电机绕线", "三花智控、拓普集团、绿的谐波", "公司口径（送样/研发）"],
      ["直线执行器", "无框电机 + 行星滚柱丝杠", "螺纹硬旋风铣削磨削、淬火与装配良率", "三花智控、拓普集团、中大力德", "公司口径（送样/研发）"],
      ["双手灵巧手", "空心杯电机 + 微型减速箱", "微型空心杯电机高功率密度、微型齿轮箱", "鸣志电器、三花智控", "公司口径（样品交付）"],
      ["传感与主控", "IMU + 力传感器 + 控制器", "六维力传感器应变片贴片与解算芯片", "汇川技术（主控）", "公司口径（技术积累）"],
      ["结构件与电池", "轻量化骨架 + 动力电池", "钛合金/铝合金精密铸造与高能量密度电池", "拓普集团（结构件）", "公司口径（量产产线）"],
    ],
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-MOONS-FILING"],
  },
];
