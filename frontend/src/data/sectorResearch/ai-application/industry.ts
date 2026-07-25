import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    "type": "paragraph",
    "text": "格局上呈现「基础模型能力提供者 + 垂直应用与分发渠道 + 海外消费应用」三股力量。A股更易映射到有用户入口或行业交付能力的公司，而非纯模型实验室（分析推断）。",
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "bullets",
    "items": [
      "科大讯飞：模型+行业应用双轮，教育医疗政务汽车等（公司口径）。",
      "金山办公：办公分发入口，AI功能服务订阅与政企（公司口径）。",
      "同花顺：金融数据与流量，AI问句与终端增值（公司口径）。",
      "拓尔思：政企知识智能与大模型应用（公司口径）。",
      "昆仑万维：AI应用矩阵与海外方向（公司口径）。"
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "table",
    "caption": "核心厂商观察矩阵",
    "headers": [
      "厂商",
      "核心入口",
      "AI看点",
      "验证指标",
      "口径"
    ],
    "rows": [
      [
        "科大讯飞",
        "行业+消费者设备",
        "星火落地与订单",
        "行业收入/毛利",
        "公司口径"
      ],
      [
        "金山办公",
        "WPS用户",
        "AI渗透与ARPU",
        "订阅与企业授权",
        "公司口径"
      ],
      [
        "同花顺",
        "金融用户",
        "AI功能付费",
        "增值服务",
        "公司口径"
      ],
      [
        "拓尔思",
        "政企客户",
        "项目落地",
        "新签与回款",
        "公司口径"
      ],
      [
        "昆仑万维",
        "消费/海外",
        "应用商业化",
        "海外收入质量",
        "公司口径"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-THS-FILING",
      "S-AIAPP-TRS-FILING",
      "S-AIAPP-KUNLUN-FILING"
    ]
  },
  {
    "type": "compareTable",
    "caption": "应用层护城河来源（内部分析）",
    "headers": [
      "来源",
      "含义",
      "可被模型厂替代性"
    ],
    "rows": [
      [
        "分发入口",
        "日活与默认工作流",
        "中（可被预装挑战）"
      ],
      [
        "行业数据",
        "专有语料与标注",
        "较低"
      ],
      [
        "合规与交付",
        "过审、私有化、集成",
        "较低"
      ],
      [
        "品牌信任",
        "高风险行业更关键",
        "中"
      ]
    ],
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-IFLYTEK-FILING",
      "S-AIAPP-GENERATIVE-AI-SERVICE"
    ]
  },
  {
    "type": "callout",
    "tone": "emphasis",
    "text": "内部分析抓手：用「付费用户/席位 × 使用深度 × 毛利率」三角验证，而不是用参数量或发布会次数。",
    "sourceIds": [
      "S-AIAPP-WPS-FILING",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  },
  {
    "type": "risk",
    "items": [
      "大厂免费或低价策略冲击独立应用。",
      "监管与备案提高上线与运营成本。",
      "算力成本与价格战双杀利润。",
      "项目制公司收入波动大。",
      "主题退潮后流动性与估值中枢下移。"
    ],
    "sourceIds": [
      "S-AIAPP-GENERATIVE-AI-SERVICE",
      "S-AIAPP-CAC",
      "S-AIAPP-IFLYTEK-FILING"
    ]
  }
];
