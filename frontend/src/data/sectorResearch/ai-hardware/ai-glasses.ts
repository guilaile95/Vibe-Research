import type { ContentBlock } from "../types.ts";

export const aiGlassesBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "AI眼镜是2024-2025年消费AI终端的最大创新方向：小米、雷鸟、Rokid、影目等密集发布AI眼镜产品，歌尔股份作为核心代工厂商受益（公司口径）。",
    sourceIds: ["S-AIHW-XIAOMI-SUPPLYCHAIN", "S-AIHW-GOERTEK-FILING"],
  },
  {
    type: "paragraph",
    text: "AI眼镜通过集成摄像头、麦克风、扬声器、光学显示模组与端侧AI芯片，实现语音交互、实时翻译、导航提示、拍照摄像等功能。相比AR眼镜，AI眼镜不强调显示功能，更侧重AI助手属性与轻量化佩戴。",
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING"],
  },
  {
    type: "compareTable",
    caption: "国内主流AI眼镜产品对比",
    headers: ["产品", "核心功能", "芯片平台", "代工厂商"],
    rows: [
      ["小米AI眼镜", "语音助手/翻译/拍照/导航", "高通AR1/自研", "歌尔股份"],
      ["雷鸟Air 3", "AI助手/翻译/拍摄", "高通AR1", "歌尔股份"],
      ["Rokid Max", "AI+AR双模/办公/影音", "RK3588", "自研/歌尔"],
      ["影目INMO GO 2", "实时翻译/导航/拍照", "高通AR1", "歌尔股份"],
    ],
    sourceIds: ["S-AIHW-XIAOMI-SUPPLYCHAIN", "S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING"],
  },
  {
    type: "bullets",
    items: [
      "歌尔股份：AI眼镜/AR光学模组与整机代工龙头，与多家海内外AI眼镜品牌深度合作（公司口径）。",
      "光学模组：光波导、Birdbath、自由曲面是AR显示核心光学方案，技术壁垒高。",
      "芯片平台：高通AR1、瑞芯微RK3588、恒玄科技BES2800是AI眼镜主流SoC方案。",
      "市场空间：机构预测2027年AI眼镜全球出货量可达数千万台级别（机构预测）。",
    ],
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING", "S-AIHW-EDGE-AI-TREND"],
  },
];
