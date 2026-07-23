import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "技术规范定义：JEDEC (JESD235C) 规范将 HBM（High Bandwidth Memory，高带宽内存）定义为通过 TSV（硅通孔）与微凸块将多层 DRAM 芯片垂直堆叠，并与逻辑 Base Die 封装在一起的超高速存储架构，打破‘内存墙’瓶颈。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "paragraph",
    text: "HBM 是目前 AI 训练与推理 GPU 的绝对标准显存配置。通过 1024-bit 超宽位宽总线，HBM3e 单颗粒带宽可突破 1.2TB/s，远超传统 GDDR6 的带宽上限。",
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-SHANNON-FILING"],
  },
  {
    type: "bullets",
    items: [
      "海外三大原厂主导：SK海力士、三星电子、美光科技垄断全球 HBM 晶圆制造与堆叠物理产能。",
      "A股映射链条（材料/分销/封测）：雅克科技（前驱体/材料）、香农芯创（海力士分销）、太极实业（封测合作）、华海诚科（GMC塑封料研发）、长电/通富（2.5D/3D封测）。",
      "特别澄清：目前无任何 A 股公司直接生产 HBM 裸芯片（DRAM Die），A 股厂商主要分布于前工序材料、分销代理与后工序先进封装/测试生态中。",
    ],
    sourceIds: ["S-HBM-YAKU-FILING", "S-HBM-SHANNON-FILING", "S-HBM-TAIJI-FILING", "S-HBM-HUAHAI-FILING", "S-HBM-JCET-FILING", "S-HBM-TFME-FILING"],
  },
  {
    type: "table",
    caption: "HBM 产业链环节与 A 股映射表",
    headers: ["产业链环节", "核心技术/部件", "代表海外原厂", "代表 A 股厂商", "事实/口径等级"],
    rows: [
      ["HBM DRAM 晶圆", "1b/1c nm 先进制程 DRAM", "SK海力士、三星、美光", "无（A股不生产裸片）", "已确认事实"],
      ["前驱体与关键材料", "High-K/金属前驱体、GMC塑封料", "默克、ADEKA", "雅克科技、华海诚科", "公司口径（送样/供应）"],
      ["分销与代理", "SK海力士芯片与HBM产品线", "不适用", "香农芯创", "公司口径（代理分销）"],
      ["2.5D/3D 封测", "CoWoS/X-DFOI/大尺寸Chiplet封测", "台积电(CoWoS)", "通富微电、长电科技、太极实业", "公司口径（封测合作）"],
    ],
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-YAKU-FILING", "S-HBM-SHANNON-FILING", "S-HBM-TAIJI-FILING", "S-HBM-HUAHAI-FILING", "S-HBM-JCET-FILING", "S-HBM-TFME-FILING"],
  },
];
