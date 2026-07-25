import type { ContentBlock } from "../types.ts";

export const architectureBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "人形机器人的架构设计需要在机械刚度、运动柔性、能量效率与算法实时性之间取得严格平衡。经典整机通常包含28~40个全身自由度（DOF），其中旋转关节与直线关节承担绝大部分载荷。",
    sourceIds: ["S-HUMANOID-INOVANCE-FILING", "S-HUMANOID-SANHUA-FILING"],
  },
  {
    type: "compareTable",
    caption: "人形机器人三大核心架构模块技术对比",
    headers: ["架构模块", "核心功能", "主要物理硬件", "当前技术突破点", "主要挑战"],
    rows: [
      ["机械传动层", "提供关节旋转与直线推力", "谐波减速器、行星滚柱丝杠、力矩电机", "高扭矩密度、轻量化铝合金/钛合金", "滚柱丝杠精密加工良率与成本"],
      ["电控驱动层", "实现电流回路与多轴高频伺服", "微型驱动器、双编码器、Bus总线", "高频PWM控制、机电一体化集成", "散热受限下的连续过载能力"],
      ["具身模型层", "环境感知、路径规划与平衡控制", "端侧SoC、六维力觉传感器、深度相机", "强化学习(RL)与End-to-End VLA大模型", "Sim2Real（仿真到现实）迁移误差"],
    ],
    sourceIds: ["S-HUMANOID-INOVANCE-FILING", "S-HUMANOID-GREENHARMONIC-FILING"],
  },
  {
    type: "bullets",
    items: [
      "力控与柔顺性：通过关节端扭矩传感器或利用电机电流环实现阻抗控制，确保机器人撞击保护与地面自适应平衡。",
      "传感器融合：结合姿态传感器（IMU）、足底/手腕六维力传感器及头部双目RGB-D相机，实现千赫兹级的姿态控制回路。",
    ],
    sourceIds: ["S-HUMANOID-MIIT-ACTION-PLAN", "S-HUMANOID-INOVANCE-FILING"],
  },
];
