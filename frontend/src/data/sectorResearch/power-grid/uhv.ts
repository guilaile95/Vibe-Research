import type { ContentBlock } from "../types.ts";

export const uhvBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "特高压是跨大区能源资源配置的骨干通道。公开政策与电网规划强调「新能源大基地 + 外送通道」组合，以提升远距离、大容量输电与消纳能力（官方口径）。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC"],
  },
  {
    type: "paragraph",
    text: "特高压按技术路线分交流（1000kV）与直流（±800kV/±1100kV）。直流在超远距离、大容量点对点外送上经济性更优，是风光大基地外送主力；交流侧重联网与受端支撑。柔性直流（VSC-HVDC）进一步适配新能源波动与多端组网（分析推断/产业共识）。",
    sourceIds: ["S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING"],
  },
  {
    type: "compareTable",
    caption: "特高压交流 vs 直流技术路线对比",
    headers: ["维度", "特高压交流（1000kV）", "特高压直流（±800kV/±1100kV）"],
    rows: [
      ["技术定位", "跨区域联网与受端落点支撑", "点对点超大容量远距离输电"],
      ["关键装备", "变压器、GIS、组合电器", "换流变压器、换流阀、控制保护"],
      ["适用距离", "中等（约数百至约千公里量级）", "更长距离、更大容量场景更优"],
      ["核心受益厂商", "平高电气、特变电工等", "许继电气、国电南瑞、特变电工等"],
      ["建设节奏特征", "与联网规划、受端需求绑定", "与大基地核准及通道规划绑定"],
    ],
    sourceIds: [
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-NANRUI-IR",
    ],
  },
  {
    type: "table",
    caption: "特高压工程关键设备与 A 股映射",
    headers: ["设备环节", "典型产品", "代表厂商", "口径"],
    rows: [
      ["开关设备", "特高压 GIS、断路器", "平高电气", "公司口径"],
      ["变压器", "特高压交流变、换流变", "特变电工", "公司口径"],
      ["换流阀/控制保护", "直流换流阀、控制保护系统", "许继电气、国电南瑞", "公司口径"],
      ["二次与自动化", "保护、监控、调度接口", "国电南瑞、四方股份", "公司口径"],
    ],
    sourceIds: [
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-SIFANG-FILING",
    ],
  },
  {
    type: "bullets",
    items: [
      "柔性直流输电适用于新能源并网、孤岛供电与多端直流电网，对电力电子与控制算法要求更高。",
      "工程链路一般为：规划核准 → 主设备招标 → 制造交付 → 调试投运；设备招标往往在核准后集中释放。",
      "「新能源 + 调节性电源打捆外送」可提高通道利用小时数，但调节资源与送端电网建设需同步（分析推断）。",
      "海外特高压/超高压总包与装备出口是部分厂商第二增长曲线，但受地缘与融资条件约束（公司口径/分析推断）。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-IR"],
  },
  {
    type: "risk",
    items: [
      "通道核准与开工进度不及预期，导致特高压设备招标空窗。",
      "柔直与换流阀等环节技术迭代快，后进入者认证与业绩门槛高。",
      "工程造价与原材料成本波动影响总包与设备商利润率。",
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-XUJI-FILING"],
  },
];
