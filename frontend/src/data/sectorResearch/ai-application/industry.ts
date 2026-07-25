import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI应用板块由「基础大模型厂商+垂直应用厂商+AI应用海外出海」三股力量构成。基础大模型走向开源与API化，垂直应用厂商凭借行业Know-How构建壁垒，海外AI应用出海则受益于全球市场空间。",
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-WPS-FILING", "S-AIAPP-KUNLUN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "科大讯飞：星火大模型+四大行业（政务/教育/医疗/汽车）垂直落地，AI开放平台开发者生态规模领先（公司口径）。",
      "金山办公：WPS AI 2.0深度嵌入办公全流程，C端付费用户与B端政企双轮驱动（公司口径）。",
      "同花顺：问财AI大模型赋能iFind金融终端，AI投顾与智能客服提升用户粘性（公司口径）。",
      "拓尔思：天渊大模型在政务/金融/媒体垂直落地，数据要素业务协同（公司口径）。",
      "昆仑万维：天工大模型+AI音乐/Mureka+AI社交/Opera AI矩阵，海外AIGC商业化领先（公司口径）。",
    ],
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-WPS-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING", "S-AIAPP-KUNLUN-FILING"],
  },
  {
    type: "table",
    caption: "AI应用核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["科大讯飞", "通用大模型+行业AI", "行业Know-Now+开发者生态", "行业落地+开放平台", "公司口径（年报披露）"],
      ["金山办公", "办公Agent", "用户基础+产品生态", "C端付费+B端政企", "公司口径（年报披露）"],
      ["同花顺", "金融AI", "金融数据+用户规模", "AI投顾+智能客服", "公司口径（年报披露）"],
      ["拓尔思", "垂直行业AI", "数据资产+行业经验", "政务/金融/媒体落地", "公司口径（年报披露）"],
      ["昆仑万维", "海外AI应用", "产品矩阵+海外渠道", "AI音乐/社交商业化", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-WPS-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING", "S-AIAPP-KUNLUN-FILING"],
  },
  {
    type: "risk",
    items: [
      "大模型迭代风险：基础大模型能力快速迭代，垂直应用厂商需持续跟进技术升级。",
      "商业化节奏风险：部分AI应用付费意愿仍待培育，商业化节奏可能低于预期。",
      "政策合规风险：生成式AI服务备案、内容安全与数据合规要求趋严。",
      "海外竞争风险：海外市场面临OpenAI/Anthropic等头部厂商直接竞争。",
    ],
    sourceIds: ["S-AIAPP-GENERATIVE-AI-SERVICE", "S-AIAPP-AGENT-TREND", "S-AIAPP-KUNLUN-FILING"],
  },
];
