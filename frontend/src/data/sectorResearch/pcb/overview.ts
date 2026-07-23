import type { ContentBlock } from "../types";

/** 总览 Tag 内容块（PCB 研究工作台）。 */
export const overviewBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI 服务器用 PCB 被产业界称为 AI 机柜的\"骨架道路\"——在 AI 算力集群从通用计算走向超大规模互连的过程中，PCB 与光互联构成机柜内两大物理层主线：光（光模块 / AOC / DAC / 光纤）承担机柜间与机柜内长距离、大带宽信号传输，PCB（印制电路板）承担芯片载板、加速卡、交换芯片、铜中板、电源板之间的电气互连、阻抗管控与功率分配。随着单柜 GPU 数量从十级走向百级、单通道速率从 56G 走向 112G/224G PAM4，PCB 正从通用高速多层板演变为 AI 壁垒最高的环节之一。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE"],
  },
  {
    type: "paragraph",
    text: "AI 机柜内 PCB 产品形态多样，按功能位置可划分为：GPU 加速卡板（如 NVIDIA GB200/GB300 Compute Board，承载 GPU 与 HBM 互连）、交换板（Switch Board，连接机柜内高速网络）、铜中板/中背板（Midplane/Backplane，正交直连前后插拔板卡，是 AI 柜内单块价值最高、技术门槛最高的 PCB 之一）、电源板（Power Board）以及传统高速背板。其中加速卡板与铜中板/中背板是狭义\"AI-PCB\"研究的核心对象，也是 2025–2026 年放量产爬坡与价值量提升的主要来源。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-HUATONG-002463", "S-SHENNAN-002916"],
  },
  {
    type: "bullets",
    items: [
      "层数跃升：通用服务器 PCB 典型 8–16 层，AI 加速卡板与铜中板普遍进入 20–50+ 层区间，压合与钻孔难度指数级上升。[产业共识量级，S-PRISMARK/S-TRENDFORCE]",
      "速率代际：从 10–25G NRZ 升级至 112G/224G PAM4，奈奎斯特频率推高至 56–112 GHz，对介质损耗与导体粗糙度要求跳升。[S-IPC-6012E/S-IPC-4101]",
      "材料升级：从 Mid-loss / FR-4 升级至 Ultra-low-loss / Super-low-loss（Df 从 ~0.005 降至 ≤0.002–0.0035 甚至更低），推动 PPO/PPE 树脂、开纤布、PTFE 混合体系需求。[S-PANASONIC-MEGTRON/S-ISOLA/S-ROGERS/S-ITEQ]",
      "线宽线距微缩：从 ≥4/4 mil 收紧至 ≤3/3 mil 以下，对 LDI 曝光、蚀刻均匀性要求显著提高。[产业共识量级]",
      "铜箔等级：从标准 ED / HVLP1 升级至 HVLP2–HVLP3（Rz 从 ~10–12 μm 降至 ≤1.5–2 μm），以抑制高频趋肤效应损耗。[S-PANASONIC-MEGTRON/S-ISOLA]",
    ],
    sourceIds: [
      "S-PRISMARK", "S-TRENDFORCE", "S-IPC-6012E", "S-IPC-4101",
      "S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-ITEQ",
    ],
  },
  {
    type: "callout",
    tone: "warning",
    text: "⚠️ 数据质量提示：AI PCB 市场空间、增速与单柜价值量是当下研究中最容易\"数字失实\"的领域。Prismark Partners、TrendForce、IDC 等机构对 2027 年 AI PCB 市场空间的预测区间跨度较大（训练期口径约 150–300 亿美元），差异主要来自统计口径（是否含 CCL、铜中板、交换板、电源板）与终端定义不同；单柜 PCB 价值量受机柜架构（GB200 NVL72 / GB300 / 自研 ASIC 机柜）组合差异影响，传闻量级从数千美元到数万美元不等。**目前公开资料尚不能确认单一数字**，本工作台对规模/增速/价值量仅作定性判断与量级锚点，不采用未经交叉验证的具体金额。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "AI-PCB 与通用服务器 PCB 典型差异对比（量级锚点，非精确值）",
    headers: ["维度", "通用服务器 PCB", "AI 服务器 PCB（加速卡/铜中板）", "备注"],
    rows: [
      ["层数", "8–16 层", "20–50+ 层", "产业共识量级，需公告核验"],
      ["单通道速率", "10–25G NRZ", "112G/224G PAM4", "速率代际，S-IPC-6012E"],
      ["材料等级", "Mid-loss / FR-4", "Ultra-low-loss / Super-low-loss", "Df 数量级差异"],
      ["线宽/线距", "≥4/4 mil", "≤3/3 mil 以下", "产业共识量级"],
      ["铜箔等级", "STD ED / HVLP1", "HVLP2–HVLP3", "Rz 量级下降"],
      ["客户认证周期", "6–12 个月", "12–24 个月", "产业共识，需公告核验"],
    ],
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-IPC-6012E", "S-IPC-4101", "S-BROKERAGE-AI-PCB"],
  },
];
