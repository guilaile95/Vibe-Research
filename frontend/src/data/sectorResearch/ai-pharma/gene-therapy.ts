import type { ContentBlock } from "../types.ts";

export const geneTherapyBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "基因治疗与细胞治疗进入商业化加速期：全球已获批20+款基因治疗/细胞治疗产品，CAR-T细胞治疗、AAV基因治疗、CRISPR基因编辑是三大主流技术路线。",
    sourceIds: ["S-PHARMA-FDA-ASCO", "S-PHARMA-BGI-FILING"],
  },
  {
    type: "paragraph",
    text: "基因治疗通过递送正常基因或编辑缺陷基因治疗遗传性疾病与癌症。华大基因在基因测序、精准医学与基因治疗领域具备全产业链能力，AI赋能基因数据分析与辅助诊断（公司口径）。",
    sourceIds: ["S-PHARMA-BGI-FILING"],
  },
  {
    type: "compareTable",
    caption: "基因治疗三大主流技术路线对比",
    headers: ["技术路线", "核心机制", "适应症", "代表产品"],
    rows: [
      ["AAV基因治疗", "腺相关病毒递送功能基因", "遗传性眼病/脊髓性肌萎缩/血友病", "Luxturna/Zolgensma/Hemgenix"],
      ["CAR-T细胞治疗", "T细胞工程化靶向癌细胞", "血液肿瘤（淋巴瘤/白血病）", "Kymriah/Yescarta/Carvykti"],
      ["CRISPR基因编辑", "精准编辑DNA序列", "遗传病/癌症/传染病", "Casgevy（首款CRISPR药物）"],
      ["mRNA疗法", "递送mRNA编码治疗蛋白", "疫苗/蛋白替代/癌症疫苗", "COVID疫苗/mRNA-4157"],
    ],
    sourceIds: ["S-PHARMA-BGI-FILING", "S-PHARMA-FDA-ASCO"],
  },
  {
    type: "bullets",
    items: [
      "华大基因：基因测序龙头，AI赋能基因数据分析、精准医学检测与基因治疗（公司口径）。",
      "CAR-T：国内已获批5+款CAR-T产品，复发/难治性血液肿瘤是核心适应症。",
      "AAV基因治疗：国内数十款AAV基因治疗药物处于临床阶段，眼科与遗传病是热点。",
      "支付挑战：基因治疗单次治疗费用高昂（百万级），医保与商业保险支付体系待完善。",
    ],
    sourceIds: ["S-PHARMA-BGI-FILING", "S-PHARMA-FDA-ASCO"],
  },
];
