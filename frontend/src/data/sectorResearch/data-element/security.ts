import type { ContentBlock } from "../types.ts";

export const securityBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "安全是流通的底线：分类分级、访问控制、隐私计算、审计与出境评估，共同决定数据「能不能动、怎么动」。深桑达A 等强调数据基础设施与安全能力结合；网信与行业监管构成外部硬约束（公司口径/官方口径）。",
    sourceIds: ["S-DATA-SANGDA-FILING", "S-DATA-20-ARTICLES", "S-DATA-CAC"],
  },
  {
    type: "table",
    caption: "数据安全与隐私保护技术/合规矩阵",
    headers: ["类别", "核心能力", "应用场景", "备注"],
    rows: [
      ["分类分级", "敏感识别、目录、策略", "治理与合规基线", "制度+工具"],
      ["隐私计算", "MPC/联邦学习/TEE 等", "联合建模、联合风控", "性能与工程化仍关键"],
      ["存证溯源", "链上/日志审计、水印", "确权与纠纷举证", "不能替代治理"],
      ["脱敏匿名", "动静态脱敏、匿名化", "测试、开放、外包", "再识别风险需评估"],
      ["出境与合规", "评估、标准合同、认证", "跨境业务", "政策敏感"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-CAC", "S-DATA-SANGDA-FILING"],
  },
  {
    type: "bullets",
    items: [
      "深桑达A：中国电子云与数据安全/数据要素相关布局，体现「云 + 安全 + 数据」组合（公司口径）。",
      "隐私计算降低明文共享需求，但计算开销与场景适配决定能否规模化（分析推断）。",
      "重要数据与个人信息出境需满足评估等要求，是跨国业务的关键路径依赖。",
      "等保、密评与行业合规（金融/医疗）往往是项目准入门槛，而非可选项。",
    ],
    sourceIds: ["S-DATA-SANGDA-FILING", "S-DATA-CAC", "S-DATA-20-ARTICLES"],
  },
  {
    type: "compareTable",
    caption: "「合规项目」vs「隐私计算产品」收入特征（内部分析）",
    headers: ["维度", "合规/安全治理项目", "隐私计算平台/产品"],
    rows: [
      ["驱动", "监管与客户审计", "联合业务价值"],
      ["销售周期", "偏项目制", "产品+方案，教育成本高"],
      ["壁垒", "资质、集成、品牌", "算法工程、生态伙伴"],
      ["风险", "预算削减", "性能不足、伪需求"],
    ],
    sourceIds: ["S-DATA-SANGDA-FILING", "S-DATA-CAC"],
  },
  {
    type: "callout",
    tone: "info",
    text: "研究提示：数据安全预算常随监管事件脉冲；更可持续的需求来自「要流通就必须合规」的制度倒逼，而非单纯安防升级口号（内部分析）。",
    sourceIds: ["S-DATA-CAC", "S-DATA-20-ARTICLES"],
  },
  {
    type: "risk",
    items: [
      "安全投入短期侵蚀数据业务利润。",
      "隐私计算概念热、落地场景少，订单验证不足。",
      "跨境规则变化导致方案重做。",
      "供应链安全与开源组件漏洞带来合规连带责任。",
    ],
    sourceIds: ["S-DATA-CAC", "S-DATA-SANGDA-FILING", "S-DATA-20-ARTICLES"],
  },
];
