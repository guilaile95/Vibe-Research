import type { ContentBlock } from "../types.ts";

export const internetBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "emphasis",
    text: "卫星互联网是商业航天最具想象空间的应用场景。通过低轨（LEO）卫星星座提供全球宽带通信、物联网、导航增强等服务。全球标杆是SpaceX Starlink（已部署7000+卫星、覆盖70+国家）；中国由中国星网（GW星座）主导建设自主可控的卫星互联网体系。",
    sourceIds: ["S-BSPACE-CHINASATNET", "S-BSPACE-ITU", "S-BSPACE-FCC"],
  },
  {
    type: "paragraph",
    text: "卫星互联网产业链按「卫星制造（平台+载荷）→ 发射服务 → 地面设备（信关站/用户终端）→ 运营与服务（宽带/物联网/导航增强）」展开。ITU（国际电信联盟）负责卫星频率/轨道资源协调，FCC（美国联邦通信委员会）负责美国商业航天许可。频率轨道资源具有稀缺性，「先用先占」原则下，星座组网的战略窗口期紧迫。",
    sourceIds: ["S-BSPACE-ITU", "S-BSPACE-FCC", "S-BSPACE-CHINASATNET"],
  },
  {
    type: "table",
    caption: "全球主要卫星互联网星座",
    headers: ["星座", "运营方", "轨道高度", "卫星数量（规划）", "进展", "事实/口径等级"],
    rows: [
      ["Starlink", "SpaceX", "340-550km", "42000+（已部署7000+）", "全球商用运营", "已确认事实"],
      ["OneWeb", "Eutelsat/OneWeb", "1200km", "634（已部署600+）", "全球覆盖", "已确认事实"],
      ["Project Kuiper", "Amazon", "590-630km", "3236（规划中）", "首批原型卫星发射", "已确认事实"],
      ["GW星座/星网", "中国星网", "LEO", "12992+（规划中）", "首批卫星已发射", "已确认事实"],
      ["G60星链", "上海垣信", "LEO", "12000+（规划中）", "首批卫星已发射", "已确认事实"],
    ],
    sourceIds: ["S-BSPACE-ITU", "S-BSPACE-FCC", "S-BSPACE-CHINASATNET"],
  },
  {
    type: "bullets",
    items: [
      "中国星网（GW星座）：2021年成立，规划12992+颗低轨卫星，是国内卫星互联网顶层主体，首批卫星已发射。",
      "银河航天：中国商业卫星互联网领先企业，已发射多颗低轨宽带通信卫星并组网试验。",
      "频率轨道资源：ITU「先用先占」原则下，中国星网/G60星链正加速组网，抢占Ka/Q/V频段轨道资源。",
      "用户终端：卫星互联网用户终端（相控间天线、模组）是产业链关键瓶颈，海格通信/华力创通/信科移动等布局。",
    ],
    sourceIds: ["S-BSPACE-CHINASATNET", "S-BSPACE-GALAXYSPACE", "S-BSPACE-ITU"],
  },
  {
    type: "risk",
    items: [
      "组网进度风险：GW星座/G60星链规划庞大，卫星研制/发射节奏存在不确定性。",
      "频谱协调风险：与Starlink/OneWeb等国际星座存在频谱重叠，ITU协调进程影响全球服务。",
      "商业变现风险：Starlink尚未盈利，国内卫星宽带资费、用户规模与商业模式仍待验证。",
    ],
    sourceIds: ["S-BSPACE-ITU", "S-BSPACE-FCC", "S-BSPACE-CHINASATNET"],
  },
];
