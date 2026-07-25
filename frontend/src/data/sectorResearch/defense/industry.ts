import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "军工行业产业格局按「军方→整机平台→分系统/设备→零部件/原材料」四层配套体系展开。整机平台（沈飞/成飞/中国船舶等）承担总装集成；分系统/设备（中航电子/中航机电/航发控制等）承担机载/舰载系统；零部件/原材料（中航光电/航天电器/航材股份等）承担基础配套。",
    sourceIds: ["S-DEF-AVICSHENFEI-2023", "S-DEF-CSSC-2023", "S-DEF-AEROSPACE-RELAY-2023", "S-DEF-AVIC-OPTO-2023", "S-DEF-AEROMATERIALS-2023"],
  },
  {
    type: "bullets",
    items: [
      "整机平台：中航沈飞（歼击机/舰载机）、中航西飞（运输机/轰炸机）、中国船舶（水面舰艇/潜艇）、航发动力（航空发动机）等。",
      "分系统/设备：中航电子（航电）、中航机电（机电）、航发控制（发动机控制）、中国动力（舰船动力）等。",
      "零部件/原材料：中航光电（连接器）、航天电器（连接器/微特电机）、航材股份（高温合金/钛合金）、光威复材（碳纤维）等。",
      "军工电子/信息化：国睿科技（雷达）、四创电子（雷达/通信）、海康威视（安防/军用视频）、卫士通（信息安全）等。",
    ],
    sourceIds: ["S-DEF-AVICSHENFEI-2023", "S-DEF-CSSC-2023", "S-DEF-AVIC-AVIATION-ENGINE-2023", "S-DEF-AEROSPACE-RELAY-2023", "S-DEF-AVIC-OPTO-2023", "S-DEF-AEROMATERIALS-2023"],
  },
  {
    type: "table",
    caption: "军工行业分层与代表A股公司",
    headers: ["分层", "定位", "核心能力", "代表公司", "事实/口径等级"],
    rows: [
      ["整机平台", "总装集成", "设计/总装/试飞/交付", "中航沈飞、中国船舶、航发动力", "公司口径（年报）"],
      ["分系统/设备", "机载/舰载系统", "航电/机电/武器/动力", "中航电子、中航机电、中国动力", "公开信息"],
      ["零部件/原材料", "基础配套", "连接器/电机/材料/元器件", "中航光电、航天电器、航材股份", "公司口径（年报）"],
      ["军工电子/信息化", "信息化配套", "雷达/通信/导航/信息安全", "国睿科技、四创电子、海康威视", "公开信息"],
    ],
    sourceIds: ["S-DEF-AVICSHENFEI-2023", "S-DEF-CSSC-2023", "S-DEF-AVIC-AVIATION-ENGINE-2023", "S-DEF-AEROSPACE-RELAY-2023", "S-DEF-AVIC-OPTO-2023", "S-DEF-AEROMATERIALS-2023"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "投资判断框架（分析推断）：军工行业投资价值排序通常为「整机平台（稀缺性+高壁垒）> 分系统/设备（高配套比例）> 零部件/原材料（高弹性+军民融合）> 军工电子/信息化（高成长+国产替代）」。整机平台具有稀缺性与高壁垒，但订单波动性较大；零部件/原材料弹性更高，军民融合打开民用空间。",
    sourceIds: ["S-DEF-AVICSHENFEI-2023", "S-DEF-CSSC-2023", "S-DEF-AVIC-OPTO-2023", "S-DEF-AEROSPACE-RELAY-2023"],
  },
];
