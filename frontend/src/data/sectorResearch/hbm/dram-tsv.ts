import type { ContentBlock } from "../types.ts";

export const dramTsvBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "物理结构门槛：12层以上 TSV 堆叠要求中介层微凸块间距降至 25μm 以下，热压键合(TCB)控制必须极其精准。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "paragraph",
    text: "HBM 的核心技术在于 TSV（Through-Silicon Via，硅通孔）与垂直堆叠。通过在 DRAM 芯片上打出数千个微米级通孔并填充金属铜，实现上下层芯片之间的高密度信号传导。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "compareTable",
    caption: "HBM 历代技术规格对比（HBM2e -> HBM3 -> HBM3e -> HBM4）",
    headers: ["代际", "堆叠层数 (Hi)", "单颗粒最大容量", "单颗粒最高带宽", "核心封装与键合技术"],
    rows: [
      ["HBM2e", "8-Hi", "16GB", "460 GB/s", "微凸块 Microbump + 传统MR-MUF"],
      ["HBM3", "8-Hi / 12-Hi", "24GB", "819 GB/s", "Advanced MR-MUF / NCF"],
      ["HBM3e", "8-Hi / 12-Hi", "24GB - 36GB", "1.2 TB/s", "Advanced MR-MUF / 优化微凸块"],
      ["HBM4 (下一代，规格待审定)", "12-Hi / 16-Hi（预测）", "36GB - 48GB（预测）", "2.0+ TB/s（预测）", "无凸块混合键合（分析推断）、接口位宽待定"],
    ],
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-SHANNON-FILING"],
  },
  {
    type: "bullets",
    items: [
      "MR-MUF 路线：SK海力士采用主导的液态环氧树脂模塑填充（MR-MUF），散热性能与散热均匀性具备显著优势。",
      "NCF 路线：传统非导电膜（NCF）在12层及更高堆叠时薄膜热压难度与气泡控制挑战剧增。",
    ],
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-HUAHAI-FILING"],
  },
];
