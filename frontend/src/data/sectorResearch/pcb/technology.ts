import type { ContentBlock } from "../types";

/** 原理与技术路线 Tag 内容块。 */
export const technologyBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI 服务器 PCB 的技术演进遵循一条核心逻辑链：速率提升 → 损耗墙 → 材料升级 → 工艺升级 → 供应商收缩。单通道速率从 28G/56G NRZ 向 112G/224G PAM4 演进，奈奎斯特频率从 14 GHz 推高至 56–112 GHz，信号在 PCB 介质与导体中的衰减（插入损耗）随频率线性上升，直接推动覆铜板树脂体系、玻纤布、铜箔粗糙度与层数/线宽工艺的全面升级。",
    sourceIds: ["S-IPC-6012E", "S-PRISMARK", "S-TRENDFORCE"],
  },
  {
    type: "paragraph",
    text: "PAM4（4-level Pulse Amplitude Modulation）是 56G+ 速率的关键调制方式：每符号承载 2 bit（vs NRZ 的 1 bit），在相同带宽下实现翻倍速率，但信噪比代价使眼图高度减半，对插入损耗与回波损耗的要求显著严于 NRZ。",
    sourceIds: ["S-IPC-6012E"],
  },
  {
    type: "table",
    caption: "速率代际与奈奎斯特频率",
    headers: ["代际", "单通道速率", "调制", "奈奎斯特频率", "典型应用"],
    rows: [
      ["28G NRZ", "28 Gbps", "NRZ", "14 GHz", "EDR / HDR 初期"],
      ["56G PAM4", "56 Gbps", "PAM4", "28 GHz", "HDR / 400G 交换机"],
      ["112G PAM4", "112 Gbps", "PAM4", "56 GHz", "NDR / 800G 交换机"],
      ["224G PAM4", "224 Gbps", "PAM4", "112 GHz", "XDR / 研发阶段"],
      ["448G PAM4", "448 Gbps", "PAM4", "224 GHz", "早期研究"],
    ],
    sourceIds: ["S-IPC-6012E", "S-PRISMARK"],
  },
  {
    type: "paragraph",
    text: "插入损耗（Insertion Loss, IL）预算是高速 PCB 设计的核心约束。在 112G PAM4 下，总 IL 预算约 -25 ~ -33 dB（含封装、连接器、通道），其中 PCB 通道 IL 在奈奎斯特频率处需控制在 ≤ -1 dB/inch 量级（背板正交区间更紧）。IL 由三部分构成：介质损耗（∝ f，Df 主导，主因）、导体损耗（∝ √f，铜箔粗糙度主导）、阻抗不连续（玻纤/树脂界面、via stub）。降低 Df 与降低铜箔粗糙度是两条主线。",
    sourceIds: ["S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-IPC-6012E"],
  },
  {
    type: "bullets",
    items: [
      "介质损耗：与频率 f 成正比，由介质损耗因子 Df 主导，是 Ultra-low-loss / Super-low-loss 材料升级的主因。[S-PANASONIC-MEGTRON/S-ISOLA/S-ROGERS/S-ITEQ]",
      "导体损耗：与 √f 成正比，由铜箔表面粗糙度 Rz 主导，HVLP2/HVLP3 升级的主因。[S-PANASONIC-MEGTRON/S-ISOLA]",
      "阻抗不连续：玻纤/树脂界面 Dk 差异（玻纤效应）与 via stub 造成，通过开纤布与背钻优化缓解。[S-IPC-6012E]",
    ],
    sourceIds: ["S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-IPC-6012E"],
  },
  {
    type: "table",
    caption: "介质 Dk / Df 要求（@1–10 GHz 量级，典型值）",
    headers: ["速率代际", "典型 Df 上限", "典型 Dk", "对应材料等级"],
    rows: [
      ["28G NRZ", "Df ≤ 0.005", "Dk 3.3–3.7", "Mid-loss（Megtron 4 / Isola I-Tera）"],
      ["56G/112G PAM4", "Df ≤ 0.002–0.0035", "Dk 3.2–3.5", "Ultra-low-loss（Megtron 6 / Isola I-Speed）"],
      ["224G PAM4", "Df ≤ 0.001–0.0015", "Dk 3.0–3.3", "Super-low-loss（Megtron 7 / 陶瓷填充 PTFE 混合）"],
      ["448G PAM4", "Df ≤ 0.001 以下", "Dk 3.0 以下", "PTFE / 特殊热塑"],
    ],
    sourceIds: ["S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-ITEQ"],
  },
  {
    type: "paragraph",
    text: "低粗糙度铜箔是抑制高频趋肤效应的关键。从 STD（Rz ~10–12 μm）→ VLP（Rz ~6–8）→ HVLP（Rz ~3–5）→ HVLP2（Rz ~2–3）→ HVLP3（Rz ≤ 1.5–2 μm）；112G 普遍要求 HVLP2 及以上，224G 推 HVLP3（行业技术共识，具体 Rz 阈值以材料厂数据手册为准）。",
    sourceIds: ["S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS"],
  },
  {
    type: "paragraph",
    text: "树脂体系、玻纤布、石英布、PTFE 混合的演进路线：传统环氧 → 改性环氧 → PPO/PPE → 氰酸酯 → PTFE 热塑。112G 主流是 PPO/PPE + 改性环氧；224G 推 PTFE 混合或全 PTFE。玻纤布从常规 E-Glass（Dk ~6.5）→ 开纤布/扁平玻纤（降低 Dk 波动、减少 skew）→ 石英/熔融石英玻纤（Dk ~3.7，配 PTFE）。玻纤效应（Fiber-weave effect）是高速板成本与良率的关键，开纤/扁平布是必要对策。",
    sourceIds: ["S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-ITEQ"],
  },
  {
    type: "callout",
    tone: "info",
    text: "关键结论：112G/224G 速率跃升直接推动材料从 Mid-loss 级跃迁至 Ultra-low-loss / Super-low-loss，铜箔从 STD/HTE 跃迁至 HVLP2/HVLP3，层数与线宽/线距要求同步收紧。这一轮升级具备'不可逆性'——一旦材料认证通过，客户不会回退到更低等级。[S-PRISMARK/S-TRENDFORCE]",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE"],
  },
  {
    type: "table",
    caption: "传统服务器 vs AI 服务器 PCB 参数对照（典型值，量级锚点）",
    headers: ["产品", "层数", "线宽/线距（mil）", "铜箔", "材料等级"],
    rows: [
      ["GPU 加速卡板（GB200/GB300）", "20–30+ 层", "≤3/3", "HVLP2-3", "Ultra-low-loss"],
      ["铜中板/中背板（Midplane）", "30–60+ 层", "≤4/4", "HVLP2-3", "Ultra-low-loss"],
      ["高速交换机板", "16–28 层", "≤3/3", "HVLP2", "Ultra-low-loss"],
      ["传统服务器板", "8–16 层", "≥4/4", "HVLP1-2", "Mid-loss"],
    ],
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-IPC-6012E"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "⚠️ 注意：上表层数/线距为行业共识量级，具体数字必须用公司公告（S-HUATONG-002463/S-SHENNAN-002916/S-SHENGHONG-300476）与机构口径（S-PRISMARK/S-TRENDFORCE）交叉验证，否则仅作量级参考。线宽/线距单位为 mil（1 mil = 25.4 μm），非 pm。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE"],
  },
];
