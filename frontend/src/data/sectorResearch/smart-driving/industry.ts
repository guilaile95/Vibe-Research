import type { ContentBlock } from "../types";

/** 芯片、算法、零部件与车企格局 Tag 内容块。 */
export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能驾驶产业格局按纵向可划分为芯片/计算平台层、算法/OS 层、传感器/零部件层与整车集成层。国内格局呈现「车企自研 Tier 1」与「独立 Tier 1」并行的格局。国际 Tier 1（Bosch、Continental、ZF、Mobileye）在传统 ADAS 与执行器领域仍占据主导地位，但在高阶域控、城市 NOA 领域，国产 Tier 1 和车企自研正在加速赶超（分析推断）。",
  },
  {
    type: "table",
    caption: "智能驾驶产业格局分层（定性）",
    headers: ["层级", "全球主导", "国内代表", "壁垒类型"],
    rows: [
      ["智驾 SoC 芯片", "NVIDIA Orin/Thor、Qualcomm Snapdragon Ride、Mobileye EyeQ 系列", "地平线（征程系列）、黑芝麻智能（武当系列）", "架构+生态+工具链壁垒"],
      ["ADAS 算法/OS", "Mobileye、QNX、Apex.AI", "中科创达（智驾 OS）、Momenta、华为", "算法+数据闭环壁垒"],
      ["域控制器（硬件）", "Bosch、Continental、ZF", "德赛西威 IPU 系列（S-DRIVE-DESAY-FILING）", "客户认证+供应链管理壁垒"],
      ["ADAS 集成/测试", "dSPACE、Vector、TRI", "经纬恒润（S-DRIVE-JINGWEI-FILING）", "工具链+仿真平台壁垒"],
      ["车载摄像头/模组", "Sony、Sunex、LG Innotek", "联创电子（S-DRIVE-LIANCHUANG-FILING）、舜宇光学", "光学设计+车规认证壁垒"],
      ["线控制动 EHB", "Bosch iBooster、Continental MK Cx、ZF", "伯特利 WCBS（S-DRIVE-BTL-FILING）", "安全冗余+车规认证+客户定点壁垒"],
      ["线控制动（研发中）", "Bosch、ZF", "亚太股份（S-DRIVE-ASIA-FILING）", "研发+认证壁垒"],
      ["多品类部件", "Bosch、Continental、Valeo", "华域汽车（S-DRIVE-HUAYU-FILING）", "规模效应+客户关系壁垒"],
    ],
    sourceIds: ["S-DRIVE-DESAY-FILING", "S-DRIVE-JINGWEI-FILING", "S-DRIVE-LIANCHUANG-FILING", "S-DRIVE-BTL-FILING", "S-DRIVE-ASIA-FILING", "S-DRIVE-HUAYU-FILING"],
  },
  {
    type: "paragraph",
    text: "分环节讨论：",
  },
  {
    type: "bullets",
    items: [
      "智驾芯片：NVIDIA Orin 是目前高阶域控的主流选择（德赛西威 IPU04/02），Thor 计划逐步接替；地平线征程 J6/J5 在国产化替代中占据领先定位，多家 Tier 1 已基于 J6 开发方案。芯片环节的壁垒不止于硬件算力，还包括工具链（CUDA/BSP/量化工具）、开发者生态与车企锁定效应（分析推断）。",
      "算法与 OS：中科创达与国内数家芯片/车厂合作开发基于 Android/Linux 的智能座舱+智驾 OS 平台，2023 年报中有提及智驾 OS 产品化进展（S-DRIVE-THUNDERSOFT-FILING）；但智驾 OS 的软件授权与 License 收费模式仍在摸索中，尚无公开的软件收入数据。",
      "域控硬件：德赛西威 IPU 系列是目前国内量产规模最大的智驾域控方案之一。2023 年报显示其智能驾驶业务实现营收 & 同比增速提升，IPU04（基于 Orin）已搭载于理想、小鹏等多款车型（S-DRIVE-DESAY-FILING）。",
      "车载镜头：联创电子车载光学业务受益于 ADAS 渗透率提升，2023 年报确认车载镜头/模组出货量增长，完成多家 Tier 1 客户认证（S-DRIVE-LIANCHUANG-FILING）。",
      "线控制动：伯特利 WCBS（One-Box 方案）是国内首个量产的线控制动产品，2023 年报显示产能规划扩张；亚太股份正在推进 EHB/EMB 的研发与客户验证（S-DRIVE-BTL-FILING；S-DRIVE-ASIA-FILING）。",
      "综合部件：华域汽车智能驾驶系统营收 2023 年实现增长，产品涵盖 24GHz/77GHz 毫米波雷达、摄像头与域控（S-DRIVE-HUAYU-FILING）。",
    ],
    sourceIds: ["S-DRIVE-DESAY-FILING", "S-DRIVE-THUNDERSOFT-FILING", "S-DRIVE-LIANCHUANG-FILING", "S-DRIVE-BTL-FILING", "S-DRIVE-ASIA-FILING", "S-DRIVE-HUAYU-FILING", "S-DRIVE-JINGWEI-FILING"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "格局判断（分析推断）：短期（2024-2026），城市 NOA 渗透率提升将直接利好域控制器（德赛西威）、传感器（联创电子、华域）与线控制动（伯特利）三个环节。「车企自研」与「独立 Tier 1」的竞争会持续加剧——长远看体量大小决定成本分摊能力，但自研车企（如华为）的垂直整合能力也可能压缩独立 Tier 1 的利润空间。",
  },
  {
    type: "callout",
    tone: "info",
    text: "以下为待验证假设：伯特利 WCBS 在 2024-2025 年的实际出货量/定点数是否超预期；德赛西威 IPU 系列在非理想品牌的外拓速度；地平线 J6 量产节奏与实际客户定点密度；中科创达智驾 OS 软件付费收入的可量化进展。上述变量影响产业格局判断的置信度。",
  },
  {
    type: "risk",
    items: [
      "车企自研 Tier 1 趋势可能导致独立 Tier 1 市场空间收窄。",
      "芯片平台切换风险：若主流方案从 Orin 迁移至 Thor/J6，域控硬件方案需重新设计与验证，带来研发摊销风险。",
      "线控制动国内份额提升速度取决于定点量产节奏，与博世产品的性能/成本竞争可能拉长替代周期。",
      "车载镜头行业进入门槛相对较低，若供给过剩可能导致毛利率承压。",
    ],
  },
];
