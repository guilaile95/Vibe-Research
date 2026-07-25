import type { ContentBlock } from "../types.ts";

export const officeAgentBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "办公Agent进入规模化落地期：金山办公WPS AI 2.0将AI写作/AI PPT/AI表格深度嵌入办公全流程，C端付费用户与B端政企客户双轮驱动（公司口径）。",
    sourceIds: ["S-AIAPP-WPS-FILING"],
  },
  {
    type: "paragraph",
    text: "办公Agent以文档处理、表格分析、会议纪要、邮件撰写等高频办公场景为切入点，通过大模型+插件+工作流编排实现端到端自动化。国内办公Agent市场由金山办公、科大讯飞、飞书等主导。",
    sourceIds: ["S-AIAPP-WPS-FILING", "S-AIAPP-IFLYTEK-FILING"],
  },
  {
    type: "compareTable",
    caption: "国内主流办公Agent产品对比",
    headers: ["产品", "核心能力", "目标用户", "商业模式"],
    rows: [
      ["WPS AI", "AI写作/PPT/表格/PDF", "C端个人+B端政企", "会员订阅+企业授权"],
      ["讯飞听见/办公本", "会议纪要/语音转写/文档生成", "商务人士+政企", "硬件+订阅"],
      ["飞书智能伙伴", "多维表格/文档/会议/项目", "中大型企业", "企业订阅"],
      ["通义千问/钉钉AI", "文档/会议/审批/项目", "中小企业+大型企业", "企业订阅"],
    ],
    sourceIds: ["S-AIAPP-WPS-FILING", "S-AIAPP-IFLYTEK-FILING"],
  },
  {
    type: "bullets",
    items: [
      "AI写作：自动生成报告、邮件、方案初稿，支持风格调整与多语言翻译。",
      "AI PPT：根据主题/大纲自动生成演示文稿，智能排版与图表生成。",
      "AI表格：自然语言查询、公式生成、数据透视与可视化。",
      "会议Agent：实时转写、摘要提取、待办事项自动分配。",
    ],
    sourceIds: ["S-AIAPP-WPS-FILING", "S-AIAPP-IFLYTEK-FILING"],
  },
];
