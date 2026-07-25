import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "商业航天是中国航天事业的重要组成部分，涵盖「火箭制造/卫星制造/卫星应用（通信/遥感/导航）」三大产业链。近年来以「朱雀二号」（蓝箭航天，全球首枚成功入轨的液氧甲烷火箭）、「GW星座/星网」（中国卫星互联网星座）、「宏图一号」（航天宏图SAR卫星星座）为代表的商业航天项目快速推进。",
    sourceIds: ["S-BSPACE-CNSA", "S-BSPACE-CHINASATNET", "S-BSPACE-LANDSPACE", "S-BSPACE-PIESAT-2023"],
  },
  {
    type: "paragraph",
    text: "商业航天按「火箭→卫星制造→卫星运营与数据应用」上下游展开。火箭是进入空间的运输工具，卫星制造是平台与载荷，卫星运营与数据应用是商业变现闭环。产业链核心环节包括：运载火箭（固体/液体/可复用）、卫星平台（CAST/Cast-space等平台型）、通信载荷（相控间天线/星间链路）、遥感载荷（SAR/光学/红外）、地面终端（终端/信关站/应用系统）。",
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023"],
  },
  {
    type: "bullets",
    items: [
      "火箭：蓝箭航天（朱雀系列液氧甲烷火箭）、星际荣耀（双曲线一号）、天兵科技（天龙系列）、中科宇航（力箭一号）等。",
      "卫星制造：中国卫星（600118，CAST平台）、航天宏图（688066，SAR卫星星座）、欧比特（300053，珠海一号）。",
      "卫星互联网：中国星网（GW星座）、银河航天（低轨宽带通信卫星）。",
      "卫星应用：天银机电（300342，雷达仿真测试/恒星敏感器）、银河电子（002519，军工/电源/雷达）。",
      "关键来源：国家航天局（CNSA）、ITU（国际电信联盟，卫星频率资源）、FCC（美国联邦通信委员会，商业航天许可）。",
    ],
    sourceIds: ["S-BSPACE-CNSA", "S-BSPACE-ITU", "S-BSPACE-FCC", "S-BSPACE-CHINASATNET", "S-BSPACE-LANDSPACE", "S-BSPACE-GALAXYSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023", "S-BSPACE-OBET-2023", "S-BSPACE-TIANYIN-2023", "S-BSPACE-YINHE-2023"],
  },
  {
    type: "table",
    caption: "商业航天产业链核心环节与代表A股/非上市公司",
    headers: ["环节", "核心产品", "代表公司", "事实/口径等级"],
    rows: [
      ["运载火箭", "固体/液体/可复用火箭", "蓝箭航天、星际荣耀、天兵科技、中科宇航", "公司口径/官方"],
      ["卫星制造（平台）", "微纳/小/中/大型卫星平台", "中国卫星（600118）、航天东方红", "公司口径（年报）"],
      ["遥感卫星星座", "SAR/光学/红外遥感星座", "航天宏图（688066）、欧比特（300053）", "公司口径（年报）"],
      ["通信卫星星座", "低轨宽带通信卫星", "银河航天、中国星网", "公司口径/官方"],
      ["地面设备与终端", "信关站/用户终端/应用系统", "海格通信、华力创通", "公开信息"],
      ["航天电子/配套", "雷达仿真/恒星敏感器/电源", "天银机电（300342）、银河电子（002519）", "公司口径（年报）"],
    ],
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023", "S-BSPACE-OBET-2023", "S-BSPACE-GALAXYSPACE", "S-BSPACE-TIANYIN-2023", "S-BSPACE-YINHE-2023"],
  },
];
