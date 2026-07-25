import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策与产业信号：工信部《电子信息制造业稳增长行动方案》支持AI眼镜、可穿戴设备、智能家居等智能终端创新。机构预测2025-2027年端侧AI芯片市场高速增长，AI眼镜/可穿戴/智能家居是核心驱动场景。",
    sourceIds: ["S-AIHW-IC-PLAN", "S-AIHW-EDGE-AI-TREND"],
  },
  {
    type: "paragraph",
    text: "AI硬件板块涵盖端侧AI芯片、AI眼镜/AR眼镜、智能可穿戴设备、智能家居终端四大方向。端侧AI推理能力下沉到消费电子终端，推动AI眼镜、TWS耳机、AI音箱、AI玩具等品类爆发式创新。",
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "bullets",
    items: [
      "端侧AI芯片：支持终端本地AI推理，降低云端延迟与隐私风险，RK3588、高通AR1、苹果Apple Silicon为代表。",
      "AI眼镜/AR眼镜：集成语音交互、导航提示、实时翻译、拍照摄像等功能，被视为下一代AI原生终端。",
      "智能可穿戴：AI手表、AI耳机、AI眼镜等产品叠加健康监测、实时翻译、运动辅助等AI能力。",
      "智能家居：AI音箱、AI摄像头、AI家电等终端智能化升级，接入大模型实现自然语言交互。",
    ],
    sourceIds: ["S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-EDGE-AI-TREND"],
  },
  {
    type: "table",
    caption: "AI硬件四大核心赛道与代表厂商",
    headers: ["赛道", "核心产品", "关键趋势", "代表A股厂商"],
    rows: [
      ["端侧AI芯片", "AIoT SoC/NPU", "低功耗、小模型部署、本地推理", "瑞芯微、全志科技、晶晨股份"],
      ["AI眼镜/AR眼镜", "光学模组/整机代工", "轻量化、长续航、多模态交互", "歌尔股份、舜宇光学、水晶光电"],
      ["智能可穿戴", "TWS/智能手表/AI耳机", "AI助手、健康监测、实时翻译", "歌尔股份、立讯精密、漫步者"],
      ["智能家居终端", "AI音箱/摄像头/家电", "大模型+IoT、自然语言交互", "科大讯飞、科沃斯、石头科技"],
    ],
    sourceIds: ["S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-GOERTEK-FILING", "S-AIHW-IFLYTEK-FILING"],
  },
];
