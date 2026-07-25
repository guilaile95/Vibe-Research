import type { ContentBlock } from "../types.ts";

export const codingAgentBlocks: ContentBlock[] = [
  {
    "type": "paragraph",
    "text": "编程Agent从代码补全扩展到测例生成、重构、排错与任务级实现，直接作用于软件工程生产率。对企业客户而言，核心矛盾是提效幅度 vs 代码泄露、供应链安全与可控部署（分析推断）。",
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "个人开发者：插件订阅与IDE集成决定渗透。",
      "企业：私有化/专有云、代码审计、权限与知识库对接是成交关键。",
      "质量评估应看合并率/返工率/缺陷率，而不是生成速度演示。",
      "与DevOps、测试平台、文档系统打通后，才从工具变成Agent。"
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  },
  {
    "type": "table",
    "caption": "编程Agent场景与价值",
    "headers": [
      "场景",
      "价值点",
      "主要风险",
      "付费意愿（定性）"
    ],
    "rows": [
      [
        "补全与生成",
        "减少样板代码",
        "风格不一致",
        "中高"
      ],
      [
        "调试排错",
        "缩短定位时间",
        "误导性建议",
        "高"
      ],
      [
        "测试生成",
        "提高覆盖率",
        "无效测试",
        "中"
      ],
      [
        "遗留系统改造",
        "降低人力",
        "幻觉改坏关键逻辑",
        "需强人工把关"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  },
  {
    "type": "compareTable",
    "caption": "通用编程助手 vs 企业定制代码助手",
    "headers": [
      "维度",
      "通用助手",
      "企业定制"
    ],
    "rows": [
      [
        "数据",
        "公网与通用语料",
        "私有仓库与规范"
      ],
      [
        "部署",
        "SaaS为主",
        "私有化/专有云常见"
      ],
      [
        "合规",
        "内容与备案",
        "代码出境、保密、审计"
      ],
      [
        "竞争",
        "国际产品强",
        "集成与安全成本土机会"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-CAC",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  },
  {
    "type": "callout",
    "tone": "info",
    "text": "A股映射上，编程Agent更多体现为软件IDE/云厂商/安全与私有化交付能力的间接受益；需避免把海外产品热度直接线性外推到国内订单（内部分析）。",
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-TRS-FILING"
    ]
  },
  {
    "type": "risk",
    "items": [
      "代码幻觉引入安全漏洞。",
      "企业禁止代码上传导致SaaS渗透受阻。",
      "开源与免费策略压制独立工具定价。",
      "评估指标缺失使ROI难证明，续费不稳。"
    ],
    "sourceIds": [
      "S-AIAPP-CAC",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  }
];
