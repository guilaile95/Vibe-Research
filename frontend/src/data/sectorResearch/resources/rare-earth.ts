import type { ContentBlock } from "../types.ts";

export const rareEarthBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "稀土监管进入条例化阶段：开采与冶炼分离纳入总量调控与追溯管理框架，行业供给弹性受政策指标约束强于普通有色品种（官方口径）。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-BEIRARE-FILING", "S-RES-GOV-PORTAL"],
  },
  {
    type: "paragraph",
    text: "稀土包含 17 种元素，产业上常分轻稀土与重稀土。中国形成「北方轻稀土 + 南方离子型重稀土」资源与冶炼格局；下游永磁（钕铁硼等）连接新能源车、风电、消费电子与军工。价格与配额、需求旺淡季、黑产整治力度高度相关（分析推断）。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING"],
  },
  {
    type: "compareTable",
    caption: "轻稀土 vs 重稀土对比",
    headers: ["维度", "轻稀土", "重稀土"],
    rows: [
      ["主要元素", "镧、铈、镨、钕等", "铽、镝、钬、钇等"],
      ["主要资源特征", "白云鄂博等混合型矿为主", "南方离子型矿，资源更稀缺"],
      ["核心应用", "永磁、催化、抛光、储氢", "高温永磁、荧光、激光、军工"],
      ["战略敏感度", "高（钕镨永磁）", "极高（镝铽等）"],
      ["代表上市平台", "北方稀土、盛和资源等", "中国稀土、广晟有色等"],
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-MIIT-RARE"],
  },
  {
    type: "table",
    caption: "稀土产业链环节与观察指标",
    headers: ["环节", "关键产出", "观察指标", "代表主体"],
    rows: [
      ["开采/冶炼分离", "稀土氧化物/金属", "总量指标、开工、库存", "北方稀土、中国稀土"],
      ["功能材料", "永磁合金/磁材坯料", "钕铁硼开工、出口、整车/风电需求", "磁材厂商（跨子板块）"],
      ["应用终端", "电机、雷达、催化等", "新能源装机、军工订单（间接）", "下游主机厂/军工"],
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "bullets",
    items: [
      "北方稀土：轻稀土龙头平台，冶炼分离与功能材料披露完整（公司口径）。",
      "中国稀土：南方离子型相关资源与冶炼布局，重稀土稀缺性更强（公司口径）。",
      "永磁是需求「锚」：新能源与人形机器人等新兴电机需求若放量，将抬升钕镨等元素弹性（推断，需销量验证）。",
      "出口与技术管控是政策工具箱组成部分，实际执行强度影响海外补库与价格（官方口径/分析推断）。",
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-MIIT-RARE"],
  },
  {
    type: "risk",
    items: [
      "总量指标与环保督察导致供给脉冲，价格暴涨暴跌。",
      "下游永磁厂库存周期放大稀土价格波动。",
      "海外稀土项目扩产若兑现，中长期改变贸易格局（时间不确定）。",
      "条例执行细则与地方指标分配的透明度有限，增加预测难度。",
    ],
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-BEIRARE-FILING"],
  },
];
