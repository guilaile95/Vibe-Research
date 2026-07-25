import type { ContentBlock } from "../types.ts";

export const codingAgentBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI编程Agent正重塑软件开发范式。从代码补全到端到端需求实现，AI编程工具可覆盖代码生成、调试、测试、重构全流程，显著提升开发者效率。",
    sourceIds: ["S-AIAPP-AGENT-TREND"],
  },
  {
    type: "compareTable",
    caption: "主流AI编程工具对比",
    headers: ["产品", "核心能力", "适用场景", "商业模式"],
    rows: [
      ["GitHub Copilot", "代码补全/对话/Agent模式", "全栈开发", "个人/企业订阅"],
      ["Cursor", "多文件编辑/Composer/Agent", "复杂项目开发", "订阅制"],
      ["Claude Code", "终端原生/长上下文推理", "系统级编程/重构", "API+订阅"],
      ["通义灵码/豆包MarsCode", "中文理解/企业定制/安全合规", "国内企业开发", "订阅/私有化部署"],
    ],
    sourceIds: ["S-AIAPP-AGENT-TREND"],
  },
  {
    type: "bullets",
    items: [
      "代码补全：实时代码建议与智能推断，减少重复性编码工作。",
      "代码对话：自然语言描述需求，生成完整函数/模块/测试用例。",
      "Agent模式：自主规划、执行、调试多步骤编程任务。",
      "代码审查：自动检测Bug、安全漏洞与性能问题。",
    ],
    sourceIds: ["S-AIAPP-AGENT-TREND"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "风险提示：1) 代码版权与合规风险（训练数据版权争议）；2) AI生成代码的安全漏洞风险；3) 工具同质化与订阅定价压力。",
    sourceIds: ["S-AIAPP-GENERATIVE-AI-SERVICE", "S-AIAPP-AGENT-TREND"],
  },
];
