import type { ContentBlock } from "../types.ts";

export const multimodalBlocks: ContentBlock[] = [
  {
    "type": "paragraph",
    "text": "多模态大模型统一处理文本、图像、音频与视频，使AIGC从写字扩展到营销素材、影视预演、工业质检与具身交互接口。商业上仍受版权、真实性与算力成本约束（分析推断）。",
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-KUNLUN-FILING",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "内容生成：广告、短视频、游戏资产制作提效显著，但平台审核与版权风险并行。",
      "理解类应用：质检、安防、文档解析等ToB场景可能比娱乐生成更易形成付费。",
      "语音多模态是讯飞等厂商传统优势向大模型迁移的接口（公司口径）。",
      "昆仑万维等在消费与海外内容AI上尝试产品矩阵（公司口径）。"
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-KUNLUN-FILING",
      "S-AIAPP-KUNLUN-IR"
    ]
  },
  {
    "type": "table",
    "caption": "多模态应用类型",
    "headers": [
      "类型",
      "示例",
      "变现",
      "主要风险"
    ],
    "rows": [
      [
        "文生图/视频",
        "营销与内容生产",
        "订阅/按量",
        "版权与平台政策"
      ],
      [
        "语音交互",
        "座舱、客服、设备",
        "授权/硬件捆绑",
        "噪声与体验"
      ],
      [
        "视觉理解",
        "质检、单据、安防",
        "项目/API",
        "场景定制成本"
      ],
      [
        "音视频理解",
        "会议、媒资检索",
        "企业订阅",
        "隐私与存储"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "compareTable",
    "caption": "生成式多模态 vs 理解式多模态",
    "headers": [
      "维度",
      "生成式",
      "理解式"
    ],
    "rows": [
      [
        "用户感知",
        "强、易传播",
        "弱、偏后台"
      ],
      [
        "监管关注",
        "内容安全高",
        "隐私与行业合规"
      ],
      [
        "付费证明",
        "创意效率",
        "错误率下降/人效"
      ],
      [
        "竞争",
        "模型与社区",
        "数据与集成"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC"
    ]
  },
  {
    "type": "callout",
    "tone": "warning",
    "text": "数据质量提示：多模态秒级生成等营销表述不等于稳定可用的生产管线；评估应看商用修订成本与法务通过率。",
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "risk",
    "items": [
      "版权诉讼与平台下架风险。",
      "推理与训练成本高，C端难盈利。",
      "深度伪造滥用引发更严监管。",
      "同质化模型导致应用层价格战。"
    ],
    "sourceIds": [
      "S-AIAPP-CAC",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  }
];
