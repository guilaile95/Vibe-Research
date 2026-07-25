import type { ContentBlock } from "../types.ts";

export const officeAgentBlocks: ContentBlock[] = [
  {
    "type": "callout",
    "tone": "info",
    "text": "办公Agent是最接近规模化付费的AI应用形态之一：把生成与改写能力嵌入文档、表格、演示等高频入口。金山办公WPS AI是A股观察办公套件AI化的核心样本（公司口径）。",
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-WPS-IR"
    ]
  },
  {
    "type": "paragraph",
    "text": "产品路径通常是「单点功能（续写/摘要）→ 多组件协同 → 工作流Agent（多步任务）」。B端还要求权限、审计、私有化与行业模板。付费验证看订阅转化、企业席位与功能使用深度，而非演示视频（分析推断）。",
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-WPS-IR"
    ]
  },
  {
    "type": "table",
    "caption": "办公Agent能力分层",
    "headers": [
      "层级",
      "典型能力",
      "用户价值",
      "商业化难点"
    ],
    "rows": [
      [
        "L1辅助生成",
        "续写、润色、摘要",
        "提效即时可感",
        "易被免费工具替代"
      ],
      [
        "L2组件智能",
        "AI表格/PPT/会议纪要",
        "减少重复劳动",
        "质量稳定性"
      ],
      [
        "L3流程Agent",
        "跨应用多步任务",
        "替代部分初级工作",
        "权限、可靠、可追责"
      ],
      [
        "L4组织知识",
        "接企业知识库与审批流",
        "组织级效率",
        "数据安全与集成成本"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "金山办公：办公入口与付费用户基础是AI功能分发优势（公司口径）。",
      "C端拼体验与价格带，B端拼安全、管理与交付。",
      "与邮件、IM、网盘、OA的连接决定Agent能否办完事。",
      "推理成本下降会改善高级功能毛利，但竞争也会加剧（分析推断）。"
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-WPS-IR"
    ]
  },
  {
    "type": "compareTable",
    "caption": "套件内AI vs 独立AI办公工具",
    "headers": [
      "维度",
      "套件内AI（如WPS AI）",
      "独立AI工具"
    ],
    "rows": [
      [
        "分发",
        "存量用户触达强",
        "需单独获客"
      ],
      [
        "数据与格式",
        "原生兼容文档生态",
        "导入导出摩擦"
      ],
      [
        "差异化",
        "工作流深度",
        "单点体验可能更极致"
      ],
      [
        "护城河",
        "许可体系+政企渠道",
        "模型与产品迭代速度"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-WPS-IR"
    ]
  },
  {
    "type": "risk",
    "items": [
      "功能同质化导致ARPU提升有限。",
      "政企采购周期长，AI附加条款谈判复杂。",
      "生成内容错误引发职业与合规风险。",
      "大模型厂商前向一体化挤压套件溢价。"
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  }
];
