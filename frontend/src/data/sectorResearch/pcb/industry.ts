import type { ContentBlock } from "../types";

/** 产业格局 Tag 内容块。 */
export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text:
      "PCB 产业按 树脂 / 玻纤布 / 铜箔 / 覆铜板 / PCB板厂 / 设备 横向展开，各环节全球主导者、国内梯队与壁垒类型差异显著：材料端由日本、美国、台湾主导，壁垒以配方与材料科学为主；板厂端台湾长期领先、国内加速追赶，壁垒以资本、工艺与客户认证为主；设备端海外主导、国产替代空间大。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "PCB 产业链全球主导、国内梯队与壁垒类型",
    headers: ["环节", "全球主导", "国内梯队", "壁垒类型", "代表企业"],
    rows: [
      [
        "树脂",
        "日本松下 Megtron、美国 Rogers、Isola 高频高速树脂全球领先",
        "仍以中低端为主，高频高速树脂仍偏依赖进口",
        "材料壁垒",
        "S-PANASONIC-MEGTRON、S-ISOLA、S-ROGERS",
      ],
      [
        "玻纤布",
        "日本NEG、台玻等主导高端超薄/ Low-Dk 玻纤布",
        "中低端基本自主，高端仍存差距",
        "材料壁垒",
        "S-ROGERS（材料体系）",
      ],
      [
        "铜箔",
        "日本三井、福田金属等主导 HVLP 电解铜箔与压延铜箔",
        "电解铜箔基本自主，RTF/HVLP 快速追赶",
        "材料+设备壁垒",
        "S-SHENGYI（铜箔&覆铜板）",
      ],
      [
        "覆铜板",
        "Panasonic、Rogers、Isola、台光、台耀主导高频高速覆铜板",
        "S-SHENGYI 已进入全球头部梯队，M4/M6 级高速材料量产",
        "材料+客户认证",
        "S-SHENGYI、S-PANASONIC-MEGTRON、S-ISOLA",
      ],
      [
        "PCB板厂（AI/高速）",
        "S-UNIMICRON、Ibiden、AT&S、Schweizer 在载板/HCoS 领先",
        "S-HUATONG-002463、S-SHENNAN-002916、S-SHENGHONG-300476 已进入 AI/服务器主流供应链，接近全球一流水准",
        "资本+工艺+客户认证",
        "S-HUATONG-002463、S-SHENNAN-002916、S-SHENGHONG-300476、S-KINWONG、S-UNIMICRON",
      ],
      [
        "PCB板厂（总体）",
        "台湾仍居全球产值首位，日本、韩国在高端载板/HDI 领先",
        "大陆 PCB 产值占全球过半，但主要集中在中低层板/HDI，高多层板仍追赶中",
        "资本+产能+客户认证",
        "S-KINWONG、S-SHENGHONG-300476、S-UNIMICRON",
      ],
      [
        "设备",
        "日本 SCHMOLL、瑞士 Posalux、美国 ESI 在钻孔/曝光/镭射居主导",
        "国产钻孔/曝光/电镀设备在中低端批量替代，高端仍依赖海外",
        "设备+工艺壁垒",
        "S-IPC-6012E（标准）",
      ],
    ],
    sourceIds: [
      "S-PANASONIC-MEGTRON",
      "S-ISOLA",
      "S-ROGERS",
      "S-ITEQ",
      "S-SHENGYI",
      "S-HUATONG-002463",
      "S-SHENNAN-002916",
      "S-SHENGHONG-300476",
      "S-KINWONG",
      "S-UNIMICRON",
      "S-PRISMARK",
      "S-TRENDFORCE",
      "S-BROKERAGE-AI-PCB",
      "S-IPC-6012E",
    ],
  },
  {
    type: "callout",
    tone: "emphasis",
    text:
      "中国 PCB 厂商整体已从'国产替代'语境进入'全球 AI 主力供应链'语境：在 AI 服务器 / 高速网络等高增长段，S-HUATONG-002463、S-SHENNAN-002916、S-SHENGHONG-300476 已通过头部客户认证并具备全球竞争力；但在上游高频高速树脂、高端玻纤布与精密设备环节，'国产替代'仍为主逻辑，全球不可替代性弱于板厂端。",
    sourceIds: [
      "S-HUATONG-002463",
      "S-SHENNAN-002916",
      "S-SHENGHONG-300476",
      "S-KINWONG",
      "S-UNIMICRON",
      "S-PANASONIC-MEGTRON",
      "S-ISOLA",
      "S-ROGERS",
      "S-PRISMARK",
      "S-TRENDFORCE",
      "S-BROKERAGE-AI-PCB",
    ],
  },
];
