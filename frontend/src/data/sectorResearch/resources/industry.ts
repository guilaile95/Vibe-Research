import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "资源卡口板块呈现「稀土/锗铟镓/锂钴镍/钨钼」四大细分赛道。北方稀土/中国稀土主导稀土开采与冶炼分离，云南锗业/株冶集团主导锗铟镓，华友钴业/天齐锂业/赣锋锂业主导锂钴镍，厦门钨业/金钼股份主导钨钼。",
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-YUNNAN-GE-FILING", "S-RES-HUAYOU-FILING", "S-RES-ZUYE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "北方稀土：轻稀土龙头，依托白云鄂博矿，稀土冶炼分离与功能材料产能行业第一（公司口径）。",
      "中国稀土：南方离子型稀土矿主导，重稀土资源稀缺性强（公司口径）。",
      "云南锗业：国内锗龙头，锗矿开采、锗材料全产业链布局（公司口径）。",
      "株冶集团：锌冶炼副产锗铟镓综合回收，锗铟镓产量国内领先（公司口径）。",
      "华友钴业：钴镍锂新能源材料一体化布局，印尼镍矿与非洲钴矿资源保障（公司口径）。",
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-HUAYOU-FILING"],
  },
  {
    type: "table",
    caption: "资源卡口核心厂商竞争力矩阵",
    headers: ["厂商", "核心资源", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["北方稀土", "轻稀土", "白云鄂博矿+总量调控", "冶炼分离+功能材料", "公司口径（年报披露）"],
      ["中国稀土", "重稀土", "南方离子型矿+稀缺性", "冶炼分离+功能材料", "公司口径（年报披露）"],
      ["云南锗业", "锗", "锗矿+全产业链", "红外/光纤/光伏锗材料", "公司口径（年报披露）"],
      ["株冶集团", "锗铟镓", "锌冶炼副产综合回收", "锗铟镓产量领先", "公司口径（年报披露）"],
      ["华友钴业", "钴镍锂", "印尼镍矿+非洲钴矿", "新能源材料一体化", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-HUAYOU-FILING"],
  },
  {
    type: "risk",
    items: [
      "价格波动风险：稀土/锗/锂/钴/镍等大宗商品价格波动较大，影响厂商盈利能力。",
      "出口管制风险：锗镓等出口管制政策调整可能影响海外销售。",
      "地缘政治风险：海外钴矿/镍矿资源所在国政策变动影响资源保障。",
      "替代技术风险：稀土永磁/锂电材料存在被替代的技术风险。",
    ],
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-HUAYOU-FILING"],
  },
];
