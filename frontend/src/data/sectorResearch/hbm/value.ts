import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "溢价逻辑：HBM3e 售价为传统 DDR5 存储的 4~6 倍，晶圆测试与 TSV 堆叠损耗大幅抬高了制造成本。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "paragraph",
    text: "HBM 售价显著高于传统 DDR5 DRAM。单颗高端 AI 加速卡（如搭载 8 颗 36GB HBM3e 的 GPU）中，HBM 存储价值量可占芯片总 BOM 的 30% 以上。",
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-SHANNON-FILING"],
  },
  {
    type: "table",
    caption: "HBM 芯片与先进封装结构价值量拆解",
    headers: ["组件/工序", "成本/价值占比", "关键技术与设备材料", "代表供应商/生态"],
    rows: [
      ["DRAM 裸晶圆 (Die)", "50% ~ 55%", "1b/1c nm DRAM 晶圆、高良率切割", "SK海力士、三星、美光"],
      ["TSV 刻蚀与镀铜", "15% ~ 20%", "深硅刻蚀设备、High-K前驱体、电镀铜", "雅克科技（前驱体）"],
      ["堆叠与晶圆键合", "12% ~ 15%", "MR-MUF 塑封机、热压键合机(TCB)", "海外专用设备商"],
      ["颗粒包封与塑封料", "5% ~ 8%", "GMC 颗粒状环氧塑封料、High-Thermal 树脂", "华海诚科（GMC研发）"],
      ["2.5D 中介层与封测", "8% ~ 10%", "Silicon Interposer、CoWoS/X-DFOI 封测", "通富微电、长电科技、太极实业"],
    ],
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-YAKU-FILING", "S-HBM-HUAHAI-FILING", "S-HBM-JCET-FILING", "S-HBM-TFME-FILING"],
  },
];
