import type { ContentBlock } from "../types.ts";

export const uhvBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "特高压是跨大区能源资源配置的核心骨干通道：国家电网已累计建成「三交九直」乃至更多特高压工程，「十四五」期间规划新增风光大基地外送通道多条（公司口径/官方披露）。",
    sourceIds: ["S-POWERGRID-SGCC-PLAN", "S-POWERGRID-NEA-14TH-FIVE"],
  },
  {
    type: "paragraph",
    text: "特高压工程按技术路线分为交流（1000kV）与直流（±800kV/±1100kV）两类。直流特高压在大容量远距离输电中经济性更优，是目前风光大基地外送的主力路线。",
    sourceIds: ["S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING"],
  },
  {
    type: "compareTable",
    caption: "特高压交流 vs 直流技术路线对比",
    headers: ["维度", "特高压交流（1000kV）", "特高压直流（±800kV/±1100kV）"],
    rows: [
      ["技术定位", "跨区域联网与受端落点支撑", "点对点超大容量远距离输电"],
      ["关键装备", "变压器、GIS、组合电器", "换流变压器、换流阀、控制保护"],
      ["造价与距离", "中等投资，适合500-1000km", "较高投资，适合1000-2500km以上"],
      ["核心受益厂商", "平高电气、特变电工", "许继电气、国电南瑞、特变电工"],
    ],
    sourceIds: ["S-POWERGRID-XUJI-FILING", "S-POWERGRID-PINGGAO-FILING", "S-POWERGRID-TEBIAN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "柔性直流输电（VSC-HVDC）是新一代技术方向，适用于新能源并网、孤岛供电与多端直流电网构建。",
      "风光大基地外送通道采用「新能源+火电打捆+特高压」的模式，提高通道利用效率与系统稳定性。",
      "特高压工程建设周期约1.5-2年，核心设备招标通常在工程核准后集中释放。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING"],
  },
];
