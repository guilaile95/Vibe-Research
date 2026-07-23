import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "产业顶层数据：中国信通院《中国算力发展指数白皮书》显示，智能算力（AI算力）已成为算力增长的核心引擎，占比超过45%。AI算力系统呈现高密度、强集群互连与高功耗液冷散热三大典型特征。",
    sourceIds: ["S-AICOMP-MIIT-WHITE-PAPER"],
  },
  {
    type: "paragraph",
    text: "AI算力研究工作台涵盖AI芯片（GPU/NPU/DCU）、AI服务器、高速交换机、网络光模块、先进封装与液冷基础设施。各子系统紧密耦合，物理形态由单卡扩展至单柜（NVL72型）乃至万卡智算集群。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "bullets",
    items: [
      "AI芯片与协处理器：海光DCU、寒武纪思元等国产算力芯片在特定智算中心快速落地（公司口径）。",
      "AI服务器整机：浪潮信息、中科曙光、紫光股份（新华三）、工业富联占据整机与代工核心市场份额（公司口径）。",
      "网络与交换机：从 400G 无损以太网/InfiniBand 向 800G/1.6T 演进，交换机结构向 Spine-Leaf 层级拓扑扩展。",
      "散热基础设施：随着单柜功耗突破 100kW，冷板式液冷与浸没式液冷渗透率快速提升。",
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-SUGON-FILING", "S-AICOMP-UNIS-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "table",
    caption: "AI算力集群核心链路与代表厂商映射表",
    headers: ["环节", "关键技术与产品", "核心指标/瓶颈", "代表A股厂商", "事实/口径等级"],
    rows: [
      ["AI服务器", "8卡/16卡高密度GPU服务器", "散热设计、供电能力、系统稳定", "浪潮信息、工业富联、中科曙光", "公司口径（年报披露）"],
      ["国产AI芯片", "通用DCU/云端AI加速卡", "内存带宽(HBM)、算力利用率、生态", "海光信息、寒武纪", "公司口径（年报披露）"],
      ["网络交换机", "800G/CPO无损以太网交换机", "背板总线带宽、缓冲区吞吐、包重传率", "紫光股份（新华三）、工业富联", "公司口径（年报披露）"],
      ["液冷基础设施", "冷板式/相变浸没式液冷系统", "PUE<1.15、冷却液绝缘性、CDU可靠性", "中科曙光、浪潮信息", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-SUGON-FILING", "S-AICOMP-UNIS-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-CAMBRICON-FILING", "S-AICOMP-HYGON-FILING"],
  },
];
