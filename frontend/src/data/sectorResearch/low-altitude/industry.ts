import type { ContentBlock } from "../types";

/**
 * 整机、零部件、空管和运营格局 Tag 内容块（低空经济研究工作台）。
 */
export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "低空经济产业格局按「整机→零部件→空管系统→运营服务」四条主线展开。当前阶段，几乎所有环节均处于「参与者众多、格局尚未收敛」的状态：既有传统航空国企（中直股份、中航高科），也有跨界汽车/科技巨头（万丰奥威、吉利旗下的沃飞长空），还有大量初创企业与新型运营公司。以下格局分析基于已读年报的公开描述与行业经验推理，具体市场份额尚无公开资料确认。（分析推断）",
    sourceIds: [
      "S-LOWALT-ZHONGZHI-FILING",
      "S-LOWALT-WANFENG-FILING",
      "S-LOWALT-AVICHIGHTECH-FILING",
    ],
  },
  {
    type: "table",
    caption: "低空经济产业格局（定性；具体市场份额尚无公开资料确认）",
    headers: ["环节", "主要参与者类型", "已核验标的（上市公司）", "竞争壁垒", "格局状态"],
    rows: [
      ["直升机整机", "传统航空国企", "中直股份（S-LOWALT-ZHONGZHI-FILING）", "型号资质+军品客户", "垄断竞争"],
      ["eVTOL 整机", "初创+跨界科技+汽车", "万丰奥威（S-LOWALT-WANFENG-FILING）", "适航认证+研发进度", "充分竞争，未收敛"],
      ["工业无人机整机", "专业无人机厂商", "纵横股份（S-LOWALT-ZONGHENG-FILING）", "产品矩阵+行业客户", "龙头初现"],
      ["复材结构件", "航空材料企业", "中航高科（S-LOWALT-AVICHIGHTECH-FILING）", "材料认证+客户关系", "寡头格局"],
      ["空管系统", "传统空管集成商", "莱斯信息（S-LOWALT-LAISI-FILING）", "行业资质+项目经验", "寡头（民用）"],
      ["通航运营", "通航运营商", "中信海直（S-LOWALT-CITIC-FILING）", "机队+客户+资质", "集中（传统通航）"],
      ["低空经济规划/基建", "交通规划咨询", "深城交（S-LOWALT-SHENCHENGJIAO-FILING）", "地方关系+项目经验", "分散→集中"],
    ],
    sourceIds: [
      "S-LOWALT-ZHONGZHI-FILING",
      "S-LOWALT-WANFENG-FILING",
      "S-LOWALT-ZONGHENG-FILING",
      "S-LOWALT-AVICHIGHTECH-FILING",
      "S-LOWALT-LAISI-FILING",
      "S-LOWALT-CITIC-FILING",
      "S-LOWALT-SHENCHENGJIAO-FILING",
    ],
  },
  {
    type: "paragraph",
    text: "eVTOL 整机格局：全球来看，Joby Aviation、Archer Aviation、Lilium 等美股上市公司处于领先；国内方面，亿航智能（EHang）先行取证，沃飞长空（吉利系）、峰飞航空（AutoFlight）、时的科技（TCab Tech）、沃兰特（Volant）等紧随其后。由于 eVTOL 仍处于适航取证和原型机阶段，尚未进入批量交付，各家的产品参数、融资节奏、适航阶段差异显著，尚未形成可量化的竞争排名。（分析推断）",
    sourceIds: ["S-LOWALT-WANFENG-FILING"],
  },
  {
    type: "paragraph",
    text: "空管与低空管理格局：空管系统具有极高的行业准入壁垒——需取得民航空管设备/系统认证，且客户关系（民航空管系统/军方/地方政府）积累深厚。莱斯信息在民航空管自动化系统领域占据较高市场份额（公司口径），正向低空管理（UTM）扩展。此外，运营商级别（电信/联通）依托 5G-A 优势切入低空通信/感知层，但与空管系统厂商形成（通信层 vs 管理层）的层次化分工。（分析推断）",
    sourceIds: ["S-LOWALT-LAISI-FILING"],
  },
  {
    type: "bullets",
    items: [
      "莱斯信息（688631）：民航空管系统龙头，低空管理/UTM 方向拓展；2023 年报提及空管业务收入与市占率情况。（公司口径，S-LOWALT-LAISI-FILING）",
      "深城交（301091）：城市交通规划龙头，延伸低空经济规划与基础设施咨询；年报提及低空经济相关业务拓展方向。（公司口径，S-LOWALT-SHENCHENGJIAO-FILING）",
      "中信海直（000099）：传统通航运营龙头，机队规模与作业收入数据可具体见年报；可能向 eVTOL 运营方向延伸。（公司口径，S-LOWALT-CITIC-FILING）",
    ],
    sourceIds: ["S-LOWALT-LAISI-FILING", "S-LOWALT-SHENCHENGJIAO-FILING", "S-LOWALT-CITIC-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证判断：整机环节（尤其 eVTOL）当前参与企业 30+，但多数在适航认证阶段会被筛除。最终收敛的格局可能参考通航制造——全球仅 5–8 家主流 eVTOL 制造商能够取得 TC 并进入批量交付，国内 3–5 家。当前万丰奥威年报中披露的 eVTOL 研发进展为方向性描述，尚无适航阶段的具体时间表。",
    sourceIds: ["S-LOWALT-WANFENG-FILING"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "判断框架（分析推断）：在低空经济早期阶段，投资价值排序逻辑通常为：拥有适航进度优势的整机厂 > 确定性受益的材料/结构件供应（如中航高科） > 空管/低空管理系统（如莱斯信息） > 运营商（如中信海直）。该排序基于壁垒高低和订单确定性，但整机厂的风险也最高（适航失败 = 价值清零），需注意整个板块仍处于早期阶段。具体投资排序不构成投资建议。",
    sourceIds: [
      "S-LOWALT-AVICHIGHTECH-FILING",
      "S-LOWALT-LAISI-FILING",
      "S-LOWALT-CITIC-FILING",
    ],
  },
  {
    type: "risk",
    items: [
      "竞争格局不确定性：eVTOL 整机领域当前玩家过多，短期内多项目同时烧钱会摊薄供应链注意力及适航审定资源。",
      "整机厂融资风险：多数 eVTOL 初创企业依赖一级市场融资，流动性收紧可能导致停摆。",
      "跨界竞争：传统航空 OEM 与新进入者之间尚未形成清晰的市场分割，潜在战局变化多。",
      "格局收敛慢：适航周期长导致格局收敛速度远慢于汽车/消费电子行业。",
      "海外竞争优势：Joby/Archer 等美股上市公司在融资和 FAA 进度上可能领先国内对标。",
    ],
  },
];
