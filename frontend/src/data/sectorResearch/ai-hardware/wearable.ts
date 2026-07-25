import type { ContentBlock } from "../types.ts";

export const wearableBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "智能可穿戴叠加AI能力形成差异化竞争：歌尔股份在TWS耳机、智能手表、AI眼镜等可穿戴代工领域具备全球竞争力（公司口径）。",
    sourceIds: ["S-AIHW-GOERTEK-FILING"],
  },
  {
    type: "paragraph",
    text: "智能可穿戴设备正从「健康监测」向「AI助手」演进。AI耳机实现实时翻译与语音助手，AI手表集成健康分析与运动教练，AI眼镜提供视觉交互与导航提示。歌尔股份作为全球可穿戴代工龙头，深度受益AI终端创新。",
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-IFLYTEK-FILING"],
  },
  {
    type: "compareTable",
    caption: "AI可穿戴设备品类与功能对比",
    headers: ["品类", "AI核心功能", "代表产品", "代工厂商"],
    rows: [
      ["AI耳机", "实时翻译/语音助手/健康监测", "科大讯飞iFLYBUDS、苹果AirPods Pro", "歌尔股份、立讯精密"],
      ["AI手表", "健康分析/运动教练/消息提醒", "Apple Watch、华为Watch、小米手表", "歌尔股份、立讯精密"],
      ["AI眼镜", "视觉交互/导航/拍照/翻译", "小米AI眼镜、雷鸟Air、Rokid", "歌尔股份"],
      ["AI胸贴/指环", "心率/血氧/睡眠监测", "Oura Ring、Whoop", "歌尔股份"],
    ],
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "bullets",
    items: [
      "歌尔股份：TWS耳机、智能手表、AI眼镜代工全球龙头，与苹果、Meta、小米等深度合作（公司口径）。",
      "AI耳机：科大讯飞iFLYBUDS系列实现会议转写、实时翻译、通话降噪等AI功能（公司口径）。",
      "健康监测：PPG心率、血氧、体温、睡眠等传感器融合AI算法，实现健康预警。",
      "市场空间：全球可穿戴设备年出货量超5亿台，AI功能渗透率持续提升。",
    ],
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-EDGE-AI-TREND"],
  },
];
