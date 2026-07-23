import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策与产业顶层目标：工信部《人形机器人创新发展指导意见》提出，到2025年人形机器人创新体系初步建立，整机达到国际先进水平，并实现批量生产；到2027年综合实力达到世界先进水平，形成安全可靠的产业链供应链体系。",
    sourceIds: ["S-HUMANOID-MIIT-ACTION-PLAN"],
  },
  {
    type: "paragraph",
    text: "人形机器人是具身智能（Embodied AI）的最佳物理载体，集成了通用人工智能算法、高功率密度机电执行器、多模态传感与精密传动系统。全机物理架构分为三大核心子系统：躯干与肢体执行器、手部灵巧驱动、算法与运控主控。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-INOVANCE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "旋转关节：采用无框力矩电机 + 谐波减速器/RV减速器 + 双编码器 + 扭矩传感器架构，负责肩、肘、腰、膝等大自由度旋转动作。",
      "直线关节：采用无框力矩电机 + 行星滚柱丝杠 / 梯形丝杠 + 位置传感器，负责腿部推力与支撑伸缩。",
      "灵巧手：采用微型空心杯电机 + 金属/塑料微型齿轮箱 + 蜗轮蜗杆 + 柔性拉线/微型丝杠，实现5-12个独立自由度抓握。",
      "感知与运控：由六维力传感器、IMU、深度视觉摄像头与端侧AI SoC构成高频闭环运控体系。",
    ],
    sourceIds: ["S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING"],
  },
  {
    type: "table",
    caption: "人形机器人核心子系统与代表厂商映射表",
    headers: ["子系统", "关键零部件", "技术门槛与瓶颈", "代表A股厂商", "事实/口径等级"],
    rows: [
      ["旋转执行器", "无框电机+谐波减速器", "传动效率、柔韧性、扭矩密度", "三花智控、拓普集团、绿的谐波", "公司口径（送样/研发）"],
      ["直线执行器", "无框电机+行星滚柱丝杠", "螺纹磨削精度、高硬度材料、产能", "三花智控、拓普集团、中大力德", "公司口径（送样/研发）"],
      ["灵巧手驱动", "空心杯电机+微型减速箱", "外径<12mm、高功率密度、响应速度", "鸣志电器、三花智控", "公司口径（样品交付）"],
      ["运控与伺服", "伺服驱动器+运动控制器", "多轴同步控制算法、实时工控总线", "汇川技术", "公司口径（技术积累）"],
    ],
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING", "S-HUMANOID-GREENHARMONIC-FILING", "S-HUMANOID-ZHONGDA-FILING", "S-HUMANOID-MOONS-FILING", "S-HUMANOID-INOVANCE-FILING"],
  },
];
