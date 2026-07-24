import type { ContentBlock } from "../types";

/** 总览 Tag 内容块（智能驾驶研究工作台）。 */
export const overviewBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能驾驶是汽车产业当前最核心的变革方向之一，涉及感知硬件（摄像头、毫米波雷达、激光雷达）、计算平台（域控制器、SoC 芯片）、决策规划软件（算法、OS）与执行机构（线控制动、转向）四个技术层面。产业链横跨芯片设计、算法开发、零部件制造与整车集成，商业模式正在从 Tier 1/Tier 2 传统供应向软件付费、数据运营延伸。",
  },
  {
    type: "paragraph",
    text: "国内智能驾驶正处于 L2+ 大规模渗透、城市 NOA 加速落地、L3 法规框架逐步成形的阶段。2023-2024 年，以华为、小鹏、理想为代表的车企将城市导航辅助驾驶（NOA）推向更多车型，Tier 1 供应商的域控制器方案逐步量产，带动感知、计算、执行各环节的升级（分析推断）。",
  },
  {
    type: "bullets",
    items: [
      "市场空间：智能驾驶产业链涉及芯片、传感器、域控制器、线控底盘、软件算法与 HPC 仿真测试等环节；整体市场规模尚无公开统一数字，不同机构口径差异大（分析推断）。",
      "政策环境：工信部 2023 年发布《国家车联网产业标准体系建设指南（智能网联汽车）》，为 L3/L4 的产品准入和法规框架提供方向性指引（S-DRIVE-MIIT-POLICY）。",
      "上市标的：本工作台覆盖 7 家 A 股核心标的——德赛西威（域控制器）、经纬恒润（ADAS 与仿真）、中科创达（智驾 OS）、伯特利（线控制动）、亚太股份（线控制动）、联创电子（车载光学）、华域汽车（多品类智能驾驶部件），均已完成 2023 年报公告读取锚定。",
      "竞争格局：国内智驾 Tier 1 分为两类——（1）车企自研主导（华为、小鹏、理想等）与（2）独立 Tier 1（德赛西威、经纬恒润、华域等）；两类在域控、算法与客户绑定上各有优势。传统国际 Tier 1（Bosch、Continental、ZF）仍是线控制动/转向的主要供应商，国内厂商正在加速替代。（分析推断）",
    ],
    sourceIds: ["S-DRIVE-MIIT-POLICY", "S-DRIVE-DESAY-FILING", "S-DRIVE-JINGWEI-FILING", "S-DRIVE-THUNDERSOFT-FILING", "S-DRIVE-BTL-FILING", "S-DRIVE-ASIA-FILING", "S-DRIVE-LIANCHUANG-FILING", "S-DRIVE-HUAYU-FILING"],
  },
  {
    type: "table",
    caption: "智能驾驶核心环节与覆盖标的（定性）",
    headers: ["环节", "赛道核心", "国内标的", "国际对标"],
    rows: [
      ["感知-摄像头", "车载镜头、模组", "联创电子（S-DRIVE-LIANCHUANG-FILING）", "Sony、Sunex"],
      ["感知-毫米波雷达", "4D 成像雷达", "华域汽车（S-DRIVE-HUAYU-FILING）", "Arbe、Continental"],
      ["感知-激光雷达", "半固态/固态", "禾赛、速腾（未上市）", "Luminar、Hesai"],
      ["计算-域控制器", "ADAS 域控", "德赛西威（S-DRIVE-DESAY-FILING）", "Bosch、Mobileye"],
      ["计算-智驾 OS", "中间件/OS 平台", "中科创达（S-DRIVE-THUNDERSOFT-FILING）", "QNX、Apex.AI"],
      ["执行-线控制动", "WCBS/ESC", "伯特利（S-DRIVE-BTL-FILING）、亚太股份（S-DRIVE-ASIA-FILING）", "Bosch iBooster、ZF"],
      ["系统集成/测试", "ADAS 集成、仿真", "经纬恒润（S-DRIVE-JINGWEI-FILING）", "dSPACE、Vector"],
      ["多品类部件", "智驾全栈部件", "华域汽车（S-DRIVE-HUAYU-FILING）", "Bosch、Continental"],
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "覆盖逻辑说明：上述 7 家标的覆盖了智能驾驶从感知→计算→执行的全链路。激光雷达厂商（禾赛、速腾）尚未纳入 A 股覆盖。华为作为重要的智驾 Tier 1（非上市公司）不在本工作台 A 股标的研究范围内。本工作台正文尚未读取全部公司年报正文，具体营收与产品数据将逐步补充。",
  },
  {
    type: "callout",
    tone: "warning",
    text: "数据质量提示：智能驾驶市场空间（渗透率、单车价值量、总规模）是机构预测误差最大的领域。不同券商对国内智驾市场规模的预测区间可能相差数倍，差异主要来自（1）智驾分级口径（是否含 L2/L2+/L3）；（2）单车价值量假设；（3）渗透率曲线斜率假设。本工作台对规模预测仅作定性判断，不采用未经交叉验证的具体数字。",
  },
];
