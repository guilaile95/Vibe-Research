import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策与产业信号：七部门《生成式人工智能服务管理暂行办法》为AI应用商业化提供合规框架。机构预测2025-2027年AI Agent将在办公、编程、客服等场景实现规模化落地，大模型应用进入价值兑现期。",
    sourceIds: ["S-AIAPP-GENERATIVE-AI-SERVICE", "S-AIAPP-AGENT-TREND"],
  },
  {
    type: "paragraph",
    text: "AI应用板块涵盖通用大模型落地、办公Agent、编程Agent、垂直行业AI应用与多模态生成四大方向。国内大模型已从参数竞赛转向场景落地，Agent智能体与多模态能力成为下一阶段核心竞争力。",
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-WPS-FILING", "S-AIAPP-KUNLUN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "通用大模型：国产大模型技术能力接近GPT-4级别，竞争焦点从参数规模转向长上下文、推理效率与Agent能力。",
      "办公Agent：WPS AI、飞书智能伙伴等将AI嵌入文档/表格/会议全流程，释放办公场景生产力。",
      "编程Agent：Copilot、Cursor等AI编程助手在国内形成开发者生态，代码生成与调试效率显著提升。",
      "垂直AI应用：金融投顾、医疗辅助、法律检索、教育个性化等场景形成差异化竞争壁垒。",
      "多模态能力：文生图、文生视频、语音克隆等AIGC应用加速商业化。",
    ],
    sourceIds: ["S-AIAPP-WPS-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING"],
  },
  {
    type: "table",
    caption: "AI应用四大核心赛道与代表厂商",
    headers: ["赛道", "核心能力", "商业化阶段", "代表A股厂商"],
    rows: [
      ["通用大模型", "对话/推理/Agent能力", "API+订阅商业化", "科大讯飞、昆仑万维"],
      ["办公Agent", "文档/表格/会议AI化", "付费用户增长", "金山办公、科大讯飞"],
      ["垂直行业AI", "行业Know-How+大模型", "订阅/项目制", "同花顺、拓尔思"],
      ["多模态AIGC", "文生图/视频/音乐", "订阅/API商业化", "昆仑万维、科大讯飞"],
    ],
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-WPS-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING", "S-AIAPP-KUNLUN-FILING"],
  },
];
