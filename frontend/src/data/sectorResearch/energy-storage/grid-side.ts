import type { ContentBlock } from "../types.ts";

export const gridSideBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "电网侧储能是2024-2025年储能市场增量主力：独立储能电站+共享储能模式推动大储项目集中释放，CNESA统计独立储能占比持续提升（官方/机构数据）。",
    sourceIds: ["S-ESA-NEA-NE-PLAN", "S-ESA-CNESA-DATA"],
  },
  {
    type: "paragraph",
    text: "电网侧储能包括独立储能电站、共享储能与电网调频储能三类。独立储能通过容量租赁、现货市场套利与容量补偿三种方式获取收益，2024年收益模式逐步清晰，项目IRR显著改善。",
    sourceIds: ["S-ESA-CNESA-DATA", "S-ESA-NEA-NE-PLAN"],
  },
  {
    type: "table",
    caption: "电网侧储能三类场景对比",
    headers: ["场景类型", "功能定位", "收益模式", "装机规模"],
    rows: [
      ["独立储能电站", "调峰/调频/备用", "容量租赁+现货套利+容量补偿", "100MW/200MWh级"],
      ["共享储能", "多主体共享容量", "容量租赁+辅助服务", "50-500MW/100-1000MWh"],
      ["调频储能", "一次调频/AGC", "辅助服务补偿", "10-50MW/5-25MWh"],
      ["新能源配储", "新能源场站配储", "减少弃电+提升消纳", "10%-20%装机+2-4小时"],
    ],
    sourceIds: ["S-ESA-CNESA-DATA", "S-ESA-NEA-NE-PLAN"],
  },
  {
    type: "bullets",
    items: [
      "收益模式：容量租赁（200-300元/kW/年）+现货市场价差套利（0.3-0.6元/kWh）+容量补偿（100-200元/kW/年）。",
      "区域差异：山东、广东、山西、湖南、宁夏等省份独立储能项目经济性较好。",
      "备案规模：2024年全国新型储能备案规模超100GWh，大储项目集中释放。",
      "风险提示：电力现货市场价格波动、容量补偿政策调整、电网消纳能力限制。",
    ],
    sourceIds: ["S-ESA-CNESA-DATA", "S-ESA-NEA-NE-PLAN"],
  },
  {
    type: "risk",
    items: [
      "电力市场改革进度风险：现货市场与辅助服务市场改革进度影响独立储能收益。",
      "容量补偿政策调整风险：若容量补偿标准下调或取消，将影响项目IRR。",
      "市场竞争加剧风险：储能EPC与设备价格战加剧，压缩厂商利润率。",
      "电网消纳风险：若电网调峰需求或新能源消纳能力不足，影响储能利用率。",
    ],
    sourceIds: ["S-ESA-NEA-NE-PLAN", "S-ESA-CNESA-DATA"],
  },
];
