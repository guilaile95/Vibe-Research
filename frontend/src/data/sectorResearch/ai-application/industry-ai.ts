import type { ContentBlock } from "../types.ts";

export const industryAiBlocks: ContentBlock[] = [
  {
    "type": "callout",
    "tone": "info",
    "text": "垂直行业AI是国内上市公司更可跟踪订单的主战场：教育、医疗、政务、汽车、金融等。科大讯飞、拓尔思、同花顺等以行业数据与渠道见长（公司口径）。",
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-THS-FILING"
    ]
  },
  {
    "type": "paragraph",
    "text": "行业AI胜负手往往是：可训练/可检索的行业语料、工作流嵌入深度、信创与安全合规、以及销售服务网络。通用模型能力是基座，但客户为业务结果付费（分析推断）。",
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-IFLYTEK-IR",
      "S-AIAPP-TRS-IR"
    ]
  },
  {
    "type": "table",
    "caption": "重点垂直场景映射",
    "headers": [
      "行业",
      "典型应用",
      "关键约束",
      "代表观察标的"
    ],
    "rows": [
      [
        "教育",
        "个性化学习、口语评测、备课",
        "内容安全、教育政策",
        "科大讯飞"
      ],
      [
        "医疗",
        "辅诊、病历、影像辅助",
        "注册与医疗责任",
        "科大讯飞等"
      ],
      [
        "政务",
        "知识库、办公、舆情",
        "信创、保密、项目制",
        "拓尔思、科大讯飞"
      ],
      [
        "金融",
        "投研问答、投顾辅助、风控",
        "适当性、合规审计",
        "同花顺"
      ],
      [
        "汽车",
        "座舱语音与智能交互",
        "车规、体验与供应",
        "科大讯飞等"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-THS-FILING"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "科大讯飞：星火+行业解决方案，是国内模型-应用一体化样本（公司口径）。",
      "同花顺：金融数据与终端用户是AI功能变现土壤（公司口径）。",
      "拓尔思：政企知识与内容智能，项目属性较强（公司口径）。",
      "成功项目常含知识库治理与流程改造，纯换模型难形成壁垒。"
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-TRS-FILING"
    ]
  },
  {
    "type": "compareTable",
    "caption": "通用大模型API vs 行业解决方案",
    "headers": [
      "维度",
      "通用API",
      "行业解决方案"
    ],
    "rows": [
      [
        "交付",
        "按token/调用",
        "项目+运维+培训"
      ],
      [
        "毛利结构",
        "云资源敏感",
        "服务与许可混合"
      ],
      [
        "客户粘性",
        "可替换",
        "流程嵌入后较高"
      ],
      [
        "A股映射",
        "云与算力更直接",
        "行业软件与讯飞等更直接"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  },
  {
    "type": "risk",
    "items": [
      "项目制导致收入季节性与回款风险。",
      "行业监管提高准入与责任成本。",
      "客户自行接入通用模型，压缩解决方案溢价。",
      "效果评估主观，续费需要可量化KPI。"
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC"
    ]
  }
];
