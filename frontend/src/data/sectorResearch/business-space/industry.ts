import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "商业航天产业格局按「火箭→卫星制造→卫星运营与数据应用」三大环节展开。火箭是进入空间的运输工具，卫星制造是平台与载荷，卫星运营与数据应用是商业变现闭环。产业链上游为火箭与卫星制造，中游为发射服务，下游为卫星运营与数据应用。",
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023", "S-BSPACE-OBET-2023"],
  },
  {
    type: "bullets",
    items: [
      "火箭：蓝箭航天（朱雀系列液氧甲烷火箭）、天兵科技（天龙系列）、星际荣耀（双曲线系列）、中科宇航（力箭一号）、星河动力（谷神星一号）等。",
      "卫星制造：中国卫星（600118，CAST平台）、航天宏图（688066，SAR星座）、欧比特（300053，高光谱）、银河航天（低轨通信卫星）。",
      "卫星互联网：中国星网（GW星座，12992+颗）、G60星链（上海垣信，12000+颗）、银河航天（商业低轨星座）。",
      "航天电子/测控：天银机电（300342）、银河电子（002519）、航天电子（600879）。",
    ],
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023", "S-BSPACE-OBET-2023", "S-BSPACE-GALAXYSPACE", "S-BSPACE-CHINASATNET", "S-BSPACE-TIANYIN-2023", "S-BSPACE-YINHE-2023", "S-BSPACE-AEROELECTRON-2023"],
  },
  {
    type: "table",
    caption: "商业航天产业分层与代表A股/非上市公司",
    headers: ["分层", "定位", "核心能力", "代表公司", "事实/口径等级"],
    rows: [
      ["火箭制造", "进入空间的运输工具", "推进/结构/复用", "蓝箭航天、天兵科技、星际荣耀", "公司口径/官方"],
      ["卫星制造", "平台+载荷", "AIT/平台/载荷", "中国卫星、航天宏图、欧比特", "公司口径（年报）"],
      ["卫星互联网星座", "全球宽带通信", "星座组网/频率轨道", "中国星网、银河航天", "官方/公司口径"],
      ["卫星遥感应用", "对地观测数据服务", "SAR/光学/处理", "航天宏图、欧比特", "公司口径（年报）"],
      ["航天电子/测控", "基础配套", "雷达/星敏/电源/惯导", "天银机电、银河电子、航天电子", "公司口径（年报）"],
    ],
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASAT-2023", "S-BSPACE-PIESAT-2023", "S-BSPACE-OBET-2023", "S-BSPACE-CHINASATNET", "S-BSPACE-GALAXYSPACE", "S-BSPACE-TIANYIN-2023", "S-BSPACE-YINHE-2023", "S-BSPACE-AEROELECTRON-2023"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "投资判断框架（分析推断）：商业航天产业当前处于「快速组网与商业化早期」阶段。火箭与卫星制造环节受益于星座组网与装备列装需求；卫星互联网环节受益于频率轨道资源抢占与政策驱动；航天电子/测控环节受益于卫星/火箭/导弹多领域配套。长期价值取决于星座组网进度、商业变现能力与频率轨道资源协调。",
    sourceIds: ["S-BSPACE-LANDSPACE", "S-BSPACE-CHINASATNET", "S-BSPACE-ITU", "S-BSPACE-PIESAT-2023", "S-BSPACE-TIANYIN-2023"],
  },
];
