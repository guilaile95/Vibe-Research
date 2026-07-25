import type { ContentBlock } from "../types.ts";

/**
 * HBM 下一代演进展望。
 * 全篇为行业预测 / 内部分析；HBM4 规格尚未形成可引用的统一官方定稿。
 * 禁止将 JEDEC 已发布的 HBM3/HBM3E 规范措辞套用为「HBM4 已确认」。
 */
export const nextGenBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "不确定性声明：本页讨论的 HBM4 / 下一代堆叠仅为行业路线图讨论与内部分析，并非已生效的统一标准文本。公开可引用的 JEDEC 规范（如 JESD235C）覆盖的是 HBM3 / HBM3E 一代；HBM4 的接口位宽、Base Die 制程、键合方式等参数在不同厂商路演与媒体报道中存在分歧，以下内容不得理解为「标准已规定」或「JEDEC 已确认」。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "callout",
    tone: "info",
    text: "HBM4 跨代演进展望（行业预测 / 内部分析 / 无官方定稿）：部分产业讨论推测，下一代方案或将接口位宽由现行 HBM3 系常见的 1024-bit 量级进一步拓宽（例如业界常提到的 2048-bit 提案口径），基础逻辑层（Base Die）亦有讨论引入更先进逻辑制程代工与无凸块混合键合（Hybrid Bonding）的可能性。上述均为未定稿预期，具体参数以未来正式标准与原厂量产规格为准。",
    sourceIds: [],
  },
  {
    type: "paragraph",
    text: "在「若 HBM4 路线图部分假设成立」的前提下，产业分析认为 Base Die 有可能更多采用逻辑晶圆代工而非传统 DRAM 工艺制造，从而推动存储原厂与晶代工厂在 2.5D / 3D Chiplet 共封上的协作加深。此段为条件性推断（内部分析，非官方定稿），不是对任何厂商量产承诺的复述，亦无官方定稿可引用。",
    sourceIds: [],
  },
  {
    type: "compareTable",
    caption:
      "【不确定 / 行业预期】HBM3e 与 HBM4 关键技术演进展望（内部分析，非标准定稿）",
    headers: [
      "技术指标",
      "HBM3e（现行一代，公开规范讨论口径）",
      "HBM4（行业预测，未定稿）",
      "对产业链可能影响（分析推断）",
    ],
    rows: [
      [
        "Base Die 工序",
        "多与 DRAM 工艺体系相关（公开讨论）",
        "逻辑晶圆代工（规划/讨论中，未确认）",
        "若成立，代工与存储原厂共封协作或加深",
      ],
      [
        "总线接口位宽",
        "1024-bit 量级（HBM3 系常见公开口径）",
        "更宽位宽提案（如 2048-bit 讨论口径，未定稿）",
        "中介层布线密度与载板要求或上升",
      ],
      [
        "堆叠键合技术",
        "微凸块（Microbump）/ MR-MUF 等（现行主流讨论）",
        "无凸块混合键合（验证/导入讨论中，未统一）",
        "对高精度键合设备与材料要求或提高",
      ],
    ],
    sourceIds: [],
  },
  {
    type: "callout",
    tone: "info",
    text: "阅读提示（内部分析）：表格右侧「HBM4」列全部为预测性表述；左侧 HBM3e 相关描述亦应与 JEDEC 等正式规范及原厂数据手册交叉核对，本页不单独构成标准解读。若后续出现正式标准文本或原厂量产规格，应以新公开文件为准并回写本页。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
];
