import type { ContentBlock } from "../types.ts";

export const edgeChipBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "端侧AI芯片是AI硬件终端的算力基石，支持在终端本地运行大模型推理，降低延迟、提升隐私性与离线能力。国内瑞芯微、全志科技、晶晨股份等厂商在AIoT SoC领域形成差异化优势。",
    sourceIds: ["S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING"],
  },
  {
    type: "table",
    caption: "国内端侧AI芯片代表产品矩阵",
    headers: ["厂商", "代表芯片", "AI算力", "目标场景"],
    rows: [
      ["瑞芯微", "RK3588/RK3588S/RV11", "6 TOPS NPU", "AIoT/AR眼镜/机器视觉/NAS"],
      ["全志科技", "R128/A733/D1", "0.5-2 TOPS", "AI音箱/智能家居/机器人"],
      ["晶晨股份", "S905X5/A311D2", "5.3 TOPS NPU", "智能机顶盒/AI音箱"],
      ["全志科技", "V853/V851", "0.2-0.8 TOPS", "智能摄像头/AI玩具"],
    ],
    sourceIds: ["S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING"],
  },
  {
    type: "bullets",
    items: [
      "瑞芯微：RK3588系列在AIoT、智能座舱、AR眼镜、机器视觉等多场景落地，RV11系列赋能端侧AI视觉（公司口径）。",
      "全志科技：R系列/A系列SoC在智能家居、机器人、AI音箱等端侧AI场景量产落地（公司口径）。",
      "关键趋势：端侧大模型部署（1-7B小模型）成为主流，NPU算力与内存带宽是核心瓶颈。",
      "应用场景：AI眼镜、智能音箱、机器人、工业视觉、智能汽车座舱等。",
    ],
    sourceIds: ["S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-EDGE-AI-TREND"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "待验证事项：1) 端侧大模型部署的实际体验与云端方案差异；2) AI眼镜等终端品类的市场渗透率拐点；3) 端侧AI芯片的国产替代节奏。",
    sourceIds: ["S-AIHW-EDGE-AI-TREND", "S-AIHW-RK-FILING"],
  },
];
