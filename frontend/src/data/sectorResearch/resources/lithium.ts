import type { ContentBlock } from "../types.ts";

export const lithiumBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "锂钴镍是动力电池核心材料：华友钴业布局非洲钴矿与印尼镍矿，天齐锂业/赣锋锂业掌控全球优质锂资源，中国锂加工产能全球占比超70%（公司口径）。",
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "paragraph",
    text: "锂、钴、镍是动力电池正极材料的核心金属。锂用于磷酸铁锂与三元正极，钴用于高能量密度三元电池，镍用于高镍三元正极提升能量密度。华友钴业、天齐锂业、赣锋锂业等在全球资源布局中占据重要地位。",
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "compareTable",
    caption: "锂钴镍资源格局对比",
    headers: ["维度", "锂", "钴", "镍"],
    rows: [
      ["核心应用", "磷酸铁锂/三元正极", "高能量密度三元", "高镍三元正极"],
      ["全球储量分布", "南美三角+澳洲+中国", "刚果(金)主导", "印尼+菲律宾+澳洲"],
      ["中国全球占比", "储量~15%，加工~70%", "冶炼~70%", "冶炼~60%"],
      ["代表A股厂商", "天齐锂业、赣锋锂业", "华友钴业、寒锐钴业", "华友钴业、盛屯矿业"],
      ["资源布局", "澳洲锂辉石+南美盐湖", "刚果(金)铜钴矿", "印尼红土镍矿"],
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "bullets",
    items: [
      "华友钴业：钴镍锂新能源材料一体化布局，印尼镍矿与非洲钴矿资源保障（公司口径）。",
      "天齐锂业：全球锂辉石龙头，控股泰利森锂矿，锂盐产能行业领先。",
      "赣锋锂业：锂盐加工龙头，锂资源多元化布局（盐湖+锂辉石+黏土）。",
      "价格波动：锂钴镍价格受供需、地缘政治与下游需求影响波动较大。",
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-MNR-MINERALS"],
  },
];
