import type { ContentBlock } from "../types";

/** 原理与技术路线 Tag 内容块。 */
export const technologyBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI 服务器 PCB 的技术演进可概括为：速率提升 → 损耗墙 → 材料升级 → 工艺升级 → 可认证供应商收缩。单通道速率从 28G/56G 向 112G/224G PAM4 演进时，可用奈奎斯特频率随波特率上升；信号在 PCB 介质与导体中的插入损耗随频率恶化，从而推动覆铜板树脂体系、玻纤布、铜箔粗糙度与层数/线宽工艺升级。（分析推断：调制与带宽关系为公开信号完整性常识，具体材料阈值尚无公开资料确认）",
  },
  {
    type: "paragraph",
    text: "PAM4（4-level Pulse Amplitude Modulation）每符号承载 2 bit（NRZ 为 1 bit），因此在相同波特率下比特率翻倍，但眼图高度减半，对插入损耗与回波损耗更敏感。奈奎斯特频率按波特率计算：baud = bit_rate / 2（PAM4），Nyquist = baud / 2 = bit_rate / 4。（分析推断）",
  },
  {
    type: "table",
    caption: "速率代际与奈奎斯特频率（分析推断；Nyquist = baud/2）",
    headers: ["代际", "单通道速率", "调制", "波特率", "奈奎斯特频率", "备注"],
    rows: [
      ["28G NRZ", "28 Gbps", "NRZ", "28 GBd", "≈ 14 GHz", "分析推断"],
      ["56G PAM4", "56 Gbps", "PAM4", "28 GBd", "≈ 14 GHz", "分析推断"],
      ["112G PAM4", "112 Gbps", "PAM4", "56 GBd", "≈ 28 GHz", "分析推断；勿与 56 GHz 混淆"],
      ["224G PAM4", "224 Gbps", "PAM4", "112 GBd", "≈ 56 GHz", "分析推断"],
      ["448G PAM4", "448 Gbps", "PAM4", "224 GBd", "≈ 112 GHz", "早期研究；分析推断"],
    ],
  },
  {
    type: "paragraph",
    text: "插入损耗（Insertion Loss, IL）预算是高速 PCB 设计的核心约束。公开设计指南中的精确 dB 预算尚无公开资料确认；定性上 IL 常分解为：介质损耗（∝ f，Df 主导）、导体损耗（∝ √f，铜箔粗糙度/趋肤效应主导）、阻抗不连续（玻纤/树脂界面、via stub）。降低 Df 与降低铜箔粗糙度是两条主线。（分析推断）",
  },
  {
    type: "bullets",
    items: [
      "介质损耗：与频率 f 成正比，由介质损耗因子 Df 主导，是 Ultra-low-loss / Super-low-loss 材料升级的主因。（分析推断）",
      "导体损耗：与 √f 成正比，由铜箔表面粗糙度主导；HVLP 系列升级的主因。（分析推断）",
      "趋肤深度：纯铜、室温近似 δ = √(ρ/πfμ)；在 56 GHz 时铜趋肤深度约 0.28 μm（分析推断，未用材料厂手册核验）。",
      "阻抗不连续：玻纤效应与 via stub 造成，开纤布与背钻是常见缓解手段。（分析推断）",
    ],
  },
  {
    type: "table",
    caption: "介质 Dk / Df 要求（量级示意，未读材料厂数据手册；分析推断）",
    headers: ["速率代际", "典型 Df 上限（未核验）", "典型 Dk（未核验）", "对应材料等级（示意）"],
    rows: [
      ["28G NRZ", "尚无公开资料确认", "尚无公开资料确认", "Mid-loss 量级"],
      ["56G/112G PAM4", "尚无公开资料确认", "尚无公开资料确认", "Ultra-low-loss 量级"],
      ["224G PAM4", "尚无公开资料确认", "尚无公开资料确认", "Super-low-loss / PTFE 混合量级"],
      ["448G PAM4", "尚无公开资料确认", "尚无公开资料确认", "PTFE / 特殊热塑（研究阶段）"],
    ],
  },
  {
    type: "paragraph",
    text: "低粗糙度铜箔用于抑制高频趋肤效应。STD → VLP → HVLP → HVLP2 → HVLP3 是常见等级阶梯；112G/224G 具体 Rz 阈值应以材料厂数据手册为准，本工作台尚未读取 Panasonic/Isola/Rogers 等手册，故不给出具体 μm 数字。（分析推断 + 待获取）",
  },
  {
    type: "paragraph",
    text: "树脂体系与玻纤路线（环氧 → 改性环氧 → PPO/PPE → PTFE 混合；E-Glass → 开纤/扁平玻纤 → 石英布）为高速板常见演进方向，但具体代际对应关系尚无公开资料确认。（分析推断）",
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF"],
  },
  {
    type: "paragraph",
    text: "公司口径（已读官网产品页）：生益科技高速产品系列覆盖超低/低/中等介质损耗材料分类，Tg≥150℃/≥170℃、CTE<3.0至>4.5、导热系数<1.0至>2.0 W/m·K；具体牌号如Synamic8GX（一般 Dk=3.62/Df=0.0016；Dk@10GHz=3.66/Df@10GHz=0.0033）、射频mmWave77(Dk3.0/Df0.0010)、mmWaveG(Dk3.15/Df0.002)、IC封装SI13U(CTE13/Tg245℃)、SI10US(CTE10/Tg280℃)等——可支撑「国内CCL龙头具备高速/射频材料能力」的定性判断，但官网未披露AI服务器板具体供货数字。",
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC"],
  },
  {
    type: "paragraph",
    text: "公司口径（已读官网产品页）：景旺电子高多层PCB最高80层、材料分级M2~M9、40:1厚径比、线宽/线距40/40μm、应用含AI服务器/交换机；SLP最高18层Anylayer、30/30μm线宽距、mSAP/amSAP工艺；AI数据中心市场自称「AI服务器PCB制造商」、70+层高多层、9阶HDI、高速板材料库。上述为产品能力表述，不等于已确认的AI机柜量产份额。",
    sourceIds: ["S-KINWONG-HLC", "S-KINWONG-SLP", "S-KINWONG-COMPUTING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "关键结论（分析推断）：速率代际上升会收紧 IL 预算，从而推动材料与铜箔等级升级，并抬高客户认证门槛。升级一旦完成通常不易回退，但「不可逆」为分析判断，非机构或公司披露。",
  },
  {
    type: "table",
    caption: "传统服务器 vs AI 服务器 PCB 参数对照（量级示意，尚无公开资料确认）",
    headers: ["产品", "层数", "线宽/线距", "铜箔", "材料等级"],
    rows: [
      ["GPU 加速卡板", "尚无公开资料确认", "尚无公开资料确认", "尚无公开资料确认", "Ultra-low-loss 量级（推断）"],
      ["铜中板/中背板", "尚无公开资料确认", "尚无公开资料确认", "尚无公开资料确认", "Ultra-low-loss 量级（推断）"],
      ["高速交换机板", "尚无公开资料确认", "尚无公开资料确认", "尚无公开资料确认", "Ultra-low-loss 量级（推断）"],
      ["传统服务器板", "尚无公开资料确认", "尚无公开资料确认", "尚无公开资料确认", "Mid-loss 量级（推断）"],
    ],
  },
  {
    type: "callout",
    tone: "warning",
    text: "注意：层数/线距/Df/Rz 等具体数字在未读取材料手册与公司公告正文前，一律标为尚无公开资料确认。线宽/线距单位为 mil（1 mil = 25.4 μm）。奈奎斯特表为波特率定义下的分析推断：112 Gbps PAM4 → 56 GBd → Nyquist ≈ 28 GHz，不是 56 GHz。",
  },
];
