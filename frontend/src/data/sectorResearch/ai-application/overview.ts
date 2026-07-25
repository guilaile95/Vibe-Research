import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    "type": "callout",
    "tone": "info",
    "text": "合规框架：七部门《生成式人工智能服务管理暂行办法》明确备案、安全评估与提供者责任，AI应用从「能做」进入「合规可运营」。产业上，办公Agent、编程Agent、垂直行业助手与多模态内容生成是当前兑现较快的几类场景（官方口径/公司口径）。",
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC"
    ]
  },
  {
    "type": "paragraph",
    "text": "AI应用板块关注「模型能力 → 工作流嵌入 → 付费转化」。基础大模型走向API/开源双轨，价值更可能沉淀在具备数据、渠道与行业know-how的应用层。国内代表路径包括讯飞行业落地、金山办公套件AI化、同花顺金融问答、拓尔思政企知识服务、昆仑万维消费与海外应用等（公司口径/分析推断）。",
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "办公Agent：写作、PPT、表格、会议纪要等嵌入高频工作流，订阅转化路径清晰。",
      "编程Agent：代码补全到任务级实现，改变软件工程人效，但对企业代码安全与私有化提出要求。",
      "行业AI：教育/医疗/政务/金融等强知识与强合规场景，拼的是数据与交付，而非参数规模口号。",
      "多模态：图文音视频理解与生成打开营销、传媒、设计等增量，版权与幻觉仍是约束。",
      "出海应用：消费级AI产品在海外支付与流量环境可能更快验证ARPU（分析推断）。"
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "table",
    "caption": "AI应用主赛道与代表厂商",
    "headers": [
      "赛道",
      "关键产品形态",
      "变现方式",
      "代表A股",
      "口径"
    ],
    "rows": [
      [
        "办公Agent",
        "套件内AI功能",
        "C端订阅+B端许可",
        "金山办公",
        "公司口径"
      ],
      [
        "行业大模型应用",
        "垂直助手/平台",
        "项目+订阅混合",
        "科大讯飞、拓尔思",
        "公司口径"
      ],
      [
        "金融AI",
        "问句检索/投顾辅助",
        "增值服务/终端",
        "同花顺",
        "公司口径"
      ],
      [
        "消费/出海AI",
        "内容与社交应用",
        "广告/订阅/内购",
        "昆仑万维",
        "公司口径"
      ],
      [
        "编程Agent",
        "IDE插件/平台",
        "席位订阅",
        "相关软件与云厂商（观察）",
        "分析推断"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "compareTable",
    "caption": "ToC应用 vs ToB行业应用（内部分析）",
    "headers": [
      "维度",
      "ToC应用",
      "ToB行业应用"
    ],
    "rows": [
      [
        "增长杠杆",
        "流量、产品体验、支付",
        "客户关系、数据、交付"
      ],
      [
        "合规重点",
        "内容安全、备案",
        "等保、行业监管、私有化"
      ],
      [
        "收入质量",
        "ARPU与留存",
        "续费与人天/许可结构"
      ],
      [
        "风险",
        "同质化与获客成本",
        "项目制回款与定制成本"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  },
  {
    "type": "risk",
    "items": [
      "幻觉与可靠性不足导致高风险场景难规模化。",
      "算力与推理成本侵蚀应用毛利。",
      "备案与内容安全监管趋严，影响上线节奏。",
      "大厂免费策略挤压独立应用定价。",
      "主题炒作期估值与订单脱节。"
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  }
];
