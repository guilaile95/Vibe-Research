import type { ContentBlock } from "../types";

/** 价值量 Tag 内容块。 */
export const valueBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI 服务器用 PCB 价值量是测算 PCB 环节在算力产业链中蛋糕占比的核心维度。与传统服务器相比，AI 加速卡在 PCB 层数、材料等级（高速/高频覆铜板）、布线密度与均流散热设计上均显著升级，带动单卡与单柜 PCB 价值量大幅提升。但需要注意：目前公开渠道并无统一的 PCB 环节 BOM 拆分，各机构估算口径差异较大，且 PCB 厂商通常以'加工费+材料'方式报价，不同客户的定制化程度导致价格高度分散。以下数字均为机构预测/产业传闻口径，非公司官方披露。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "单颗加速卡 PCB 价值量估算（机构预测区间）",
    headers: ["维度", "传统 GPU 卡", "当前一代 AI 加速卡", "下一代 AI 加速卡"],
    rows: [
      ["层数", "10–16 层", "20–30 层", "30+ 层"],
      ["材料等级", "Mid-Low Loss", "Very Low Loss / Ultra Low Loss", "Ultra Low Loss / PTFE 混合"],
      ["面积/尺寸", "标准 ATX", "OAM/UBB 定制大尺寸", "更大尺寸 + 背钻优化"],
      ["估算 PCB 价值量", "数百美元", "数百至1000+ USD", "1000–2000+ USD"],
    ],
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "⚠️ 区间提示：单颗加速卡 PCB 价值量的公开估算区间极宽（数百至1000+ USD），差异主要来自层数（20–30+）、材料等级（Very Low Loss vs Ultra Low Loss）与是否包含背钻/定制。目前公开资料尚不能确认单一精确数字，本表数字为机构预测/产业传闻口径。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "paragraph",
    text: "单柜（Rack）层面的 PCB 价值量更为集中。以当前主流量产 AI 服务器机柜（如 8 卡推理/训练柜、8 卡 OAM 柜）为参考，单柜内 PCB 总价值量（含加速卡板、交换板、铜中板/中背板、电源板、传统高速背板）处于数万美元量级；其中铜中板/中背板因层数最高、材料最贵，单柜内占比显著。但具体数字受机柜架构组合影响显著，上述为机构预测区间，非公司披露。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "compareTable",
    caption: "上一代 vs 新一代 AI 服务器 PCB 对比（量级锚点）",
    headers: ["维度", "上一代（如 HGX H100 8卡）", "当前一代（如 GB200/GB300）", "下一代"],
    rows: [
      ["层数", "16–24 层", "20–50+ 层", "50+ 层"],
      ["材料", "Mid-Low / Low Loss", "Very Low / Ultra Low Loss", "Ultra Low Loss / PTFE"],
      ["布线密度", "标准", "高密度 + 背钻", "更高密度 + 优化背钻"],
      ["单卡价值量级", "数百美元", "数百至1000+ USD", "1000–2000+ USD"],
      ["供应商", "分散", "集中（头部 HDI/载板）", "更集中"],
    ],
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "paragraph",
    text: "覆铜板（CCL）是 PCB 的核心原材料，占 PCB 材料成本约 30–40%，占成品 PCB 价值约 15–25%（机构估算区间，口径差异大）。AI 服务器 PCB 向 Ultra-low-loss / Super-low-loss 升级，是 CCL 环节量价齐升的核心驱动力。",
    sourceIds: ["S-SHENGYI", "S-PRISMARK", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "覆铜板材料单价变化趋势（公开报价/机构估算，非实际成交价）",
    headers: ["材料等级", "典型 Df", "相对 FR-1 倍增", "主要应用"],
    rows: [
      ["FR-4", "~0.020", "1x", "消费电子 / 低端"],
      ["Mid-Low Loss", "~0.005–0.010", "3–5x", "通用服务器 / 网络"],
      ["Very Low Loss", "~0.002–0.0035", "8–15x", "高速交换机 / 高端服务器"],
      ["Ultra Low Loss / Super-low-loss", "≤0.001–0.002", "15–30x", "AI 加速卡 / 铜中板"],
    ],
    sourceIds: ["S-SHENGYI", "S-PANASONIC-MEGTRON", "S-ISOLA", "S-ROGERS", "S-ITEQ", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "AI 机柜内主要环节价值量横向比较（静态估算，量级锚点）",
    headers: ["环节", "单柜价值量级", "占比", "供给约束程度"],
    rows: [
      ["GPU", "数千万美元", "~30–40%", "极高"],
      ["HBM", "数百万美元", "~15–25%", "高"],
      ["PCB（含 CCL）", "数百万美元", "~3–8%", "中"],
      ["电源（PSU）", "数十至百万美元", "~3–5%", "中"],
      ["散热（液冷）", "数十万美元", "~2–4%", "低–中"],
      ["机柜/结构", "数十万美元", "~2–3%", "低"],
    ],
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "最终判断：PCB 环节在 AI 机柜中价值量占比约 3–8%，属于'中等占比'环节。其增长逻辑主要来自三层叠加：（1）AI 服务器出货量增长；（2）单卡/单柜 PCB 价值量升级（层数+材料）；（3）高端覆铜板渗透率提升。但需注意：PCB 环节并非 GPU/HBM 级别的'供给约束'环节，产能扩张相对容易，且加工费模式下原材料成本可部分转嫁。因此 PCB 厂商的利润增长更多来自'量价齐升'中的'价'（ASP 提升），而非'量'的稀缺溢价。需区分'真实利润增长'与'仅价值量叙事'——前者需看到毛利率与 ASP 同步提升，后者仅停留在'AI 服务器市场大所以 PCB 蛋糕大'的推演。",
    sourceIds: [
      "S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB",
      "S-SHENNAN-002916", "S-HUATONG-002463", "S-SHENGHONG-300476", "S-SHENGYI",
    ],
  },
  {
    type: "risk",
    items: [
      "单颗加速卡 PCB 价值量估算区间极宽（数百至1000+ USD），不同机构口径差异大；静态估算未包含加工费波动、良率损失与一次性工程费用（NRE）。",
      "覆铜板单价数据多为公开渠道报价或机构估算，非实际成交价格；高端 CCL 实际成交价受订单规模、客户等级影响显著。",
      "PCB 厂商年报通常不披露单卡/单柜 PCB 价值量，上述数字均为机构预测/产业传闻，非公司口径。",
      "AI 服务器 PCB 价值量占比（3–8%）为静态估算，若 GPU/HBM 价格继续上涨，PCB 占比被动下降；反之若 PCB ASP 提升快于芯片降价，占比上升。",
      "PCB 环节产能扩张相对容易（扩产周期 12–24 个月），难以形成 GPU/HBM 级别的供给约束溢价；利润增长需依赖 ASP 提升而非量增。",
    ],
    sourceIds: [
      "S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB",
      "S-SHENNAN-002916", "S-HUATONG-002463", "S-SHENGHONG-300476", "S-SHENGYI",
    ],
  },
];
