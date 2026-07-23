import type { ContentBlock } from "../types.ts";

export const architectureBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI算力系统架构由‘计算层-存储层-网络层-散热层’四位一体构成。万亿参数大模型的并行训练对算力节点的通信延时与总线带宽要求极其苛刻。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-MIIT-WHITE-PAPER"],
  },
  {
    type: "compareTable",
    caption: "传统通用计算 vs AI智算集群架构对比",
    headers: ["维度", "通用计算服务器", "AI智算服务器/机柜", "主要技术瓶颈"],
    rows: [
      ["芯片配置", "2颗通用CPU", "8-72颗算力GPU/DCU + 2颗CPU", "芯片间互连带宽与HBM内存容量"],
      ["网络拓扑", "10G/25G以太网，南北向流量为主", "400G/800G InfiniBand/RoCE，东西向集群流量", "网络丢包导致的GPU等待与Pipeline阻塞"],
      ["功耗与散热", "单机300W-800W，风冷为主", "单机2kW-10kW，单柜可达40kW-120kW，必须液冷", "热流密度极高，风冷散热物理极限突破"],
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-SUGON-FILING"],
  },
  {
    type: "bullets",
    items: [
      "算力互联总线：采用 NVLink/PCIe 5.0/6.0 及自研通信总线实现 GPU 之间高带宽直接对等访问（Peer-to-Peer）。",
      "内存扩展：通过 HBM 堆叠结合 CXL 拓展内存池，降低大模型 KV Cache 占用的显存瓶颈。",
    ],
    sourceIds: ["S-AICOMP-HYGON-FILING", "S-AICOMP-CAMBRICON-FILING"],
  },
];
