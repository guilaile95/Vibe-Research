import type { ContentBlock } from "../types";

/** 感知、计算、规划与线控 Tag 内容块。 */
export const architectureBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能驾驶系统架构按功能逻辑分为四个层级：感知层（摄像头、毫米波雷达、激光雷达、超声波雷达）、计算决策层（域控制器、SoC 芯片、ADAS 算法）、规划控制层（路径规划、行为决策、运动控制）、执行层（线控制动、线控转向、驱动控制）。系统从感知输入到执行输出形成闭环。",
  },
  {
    type: "paragraph",
    text: "当前行业趋势是从分布式 ECU 向集中式域控制器（Domain Controller / Central Compute）演进。典型方案为「行泊一体」或「舱驾一体」域控，集成了 SoC（如 Orin、Snapdragon Ride、地平线 J6）、MCU（如 Infineon TC3xx）以及以太网交换机芯片。高阶方案进一步走向中央计算+区域控制器架构（分析推断）。",
  },
  {
    type: "bullets",
    items: [
      "感知层：摄像头是目前最成熟的感知方案，车载镜头要求高动态范围（HDR）、宽温域与高可靠性；毫米波雷达正从 24GHz 向 77GHz+4D 成像升级；激光雷达（半固态/Flash/转镜）分辨率与成本仍在大幅变化中，尚无收敛趋势（分析推断）。",
      "计算层：域控制器是智驾系统「大脑」，德赛西威 IPU 系列覆盖从高算力（Orin）到中低算力（TDA4/J6）的全系方案；经纬恒润 ADAS 产品线覆盖感知融合到决策规划的全栈能力（S-DRIVE-DESAY-FILING；S-DRIVE-JINGWEI-FILING）。",
      "决策规划：以高精地图/无图方案为基础，融合 rule-based 和 learning-based 方法；端到端（E2E）模型近年成为行业热点，但在安全验证与长尾场景上仍存挑战（分析推断；待验证）。",
      "执行层：线控制动（Brake-by-Wire）是智驾执行的关键瓶颈。传统液压制动响应时延不能满足 L3 以上制动要求。伯特利 WCBS（线控制动产品）、亚太股份线控制动研发布局均为国产替代方向；Bosch iBooster 仍是全球主力方案（S-DRIVE-BTL-FILING；S-DRIVE-ASIA-FILING）。",
      "线控转向（Steer-by-Wire）：L3+ 等级要求方向盘与转向机构解耦，允许自动驾驶系统直接控制转向。国内尚无大规模量产案例，博世/采埃孚等国际 Tier 1 领先（分析推断）。",
    ],
    sourceIds: ["S-DRIVE-DESAY-FILING", "S-DRIVE-JINGWEI-FILING", "S-DRIVE-BTL-FILING", "S-DRIVE-ASIA-FILING"],
  },
  {
    type: "table",
    caption: "智能驾驶感知技术路线对比（定性；具体性能参数尚无公开资料确认）",
    headers: ["维度", "摄像头", "毫米波雷达", "激光雷达"],
    rows: [
      ["主要功能", "目标识别（车道线/车辆/行人/交通标志）", "测距/测速（中长距）", "3D 点云感知（高精度）"],
      ["分辨率", "高（图像级）", "中（角分辨率有限）", "高（点云级）"],
      ["全天候能力", "弱（依赖光照/天气）", "强（不受雨雾/光照影响）", "中（受雨雾/烟雾影响）"],
      ["成本区间", "低（百元级）", "中（千元级）", "高（数千元级，正快速下降）"],
      ["国产化程度", "较高（联创电子等）", "中等（华域等）", "中等（禾赛/速腾）"],
      ["L3+ 必要性", "必需", "必需", "视方案而定"],
    ],
  },
  {
    type: "table",
    caption: "线控制动技术路线对比（定性）",
    headers: ["方案", "技术特点", "国内代表", "国际代表"],
    rows: [
      ["EHB（电子液压制动）", "保留液压管路，电机+主缸替代真空助力器", "伯特利 WCBS（S-DRIVE-BTL-FILING）", "Bosch iBooster、Continental MK Cx"],
      ["EMB（电子机械制动）", "完全取消液压，电机直接夹紧制动盘", "亚太股份（S-DRIVE-ASIA-FILING）", "Bosch、ZF、Brembo"],
      ["ESC/ESP 集成制动", "基于现有 ESC 系统的附加制动功能", "伯特利 ESC（S-DRIVE-BTL-FILING）", "Bosch ESP、Continental ESC"],
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "技术路线上需要注意：激光雷达的「必需性」在智驾行业中存在较大分歧——纯视觉方案（Mobileye、Tesla）与多传感器融合方案各执一词；中国市场因政策/路况倾向于多传感器融合。线控制动方面，EMB 由于法规要求冗余制动，量产仍需时间，EHB 将在 L3/L4 前期仍为主流（分析推断）。",
  },
  {
    type: "risk",
    items: [
      "激光雷达技术路线仍不收敛：半固态、Flash、FMCW 等方案在成本与性能间尚未达成行业共识。",
      "线控执行（EMB）的安全冗余法规尚未明确：国内 L3/L4 法规对线控制动的冗余要求可能影响量产节奏。",
      "端到端智驾方案的安全验证方法论仍在探索中，尚无统一标准。",
    ],
  },
];
