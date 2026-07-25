import type { ContentBlock } from "../types.ts";

export const chuhaiBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "emphasis",
    text: "「出海」是中国创新药产业升级的核心路径。典型模式包括：自主海外注册（如百济泽布替尼FDA获批）、对外授权（out-license，如荣昌RC48授权Seagen 26亿美元）、联合开发（co-development）与海外商业化。",
    sourceIds: ["S-DRUG-BEIGENE-2023-FILING", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-FDA-ORANGE-BOOK"],
  },
  {
    type: "paragraph",
    text: "2023-2024年，中国创新药对外授权（out-license）交易数量与金额显著增长，交易对手多为全球TOP20 Biopharma，涉及ADC、双抗、细胞治疗等前沿领域。出海授权不仅带来首付款与里程碑收入，更通过海外临床推进与商业化分成分享全球市场收益。",
    sourceIds: ["S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASCO-LIBRARY"],
  },
  {
    type: "table",
    caption: "近年代表性中国创新药出海授权/注册案例",
    headers: ["公司", "药物/平台", "交易对手", "交易类型与金额", "事实/口径等级"],
    rows: [
      ["荣昌生物", "RC48（HER2 ADC）", "Seagen（辉瑞）", "对外授权：26亿美元（首付款+里程碑+销售分成）", "已确认事实"],
      ["百济神州", "泽布替尼（BTK）", "自主注册", "FDA/NMPA/EMA全球获批，2023全球销售额超13亿美元", "已确认事实"],
      ["百济神州", "替雷利珠单抗（PD-1）", "诺华", "对外授权海外权益（最高22亿美元）", "已确认事实"],
      ["恒瑞医药", "卡瑞利珠单抗+法米替尼", "美国Treeline Biosciences", "对外授权：最高11.6亿美元", "已确认事实"],
      ["传奇生物（金斯瑞）", "西达基奥仑赛（CAR-T）", "强生", "共同开发：最高里程碑+销售分成", "已确认事实"],
    ],
    sourceIds: ["S-DRONG-RCHANG-2023-FILING", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-GENSCRIPT-ANNUAL-2023", "S-DRUG-FDA-ORANGE-BOOK"],
  },
  {
    type: "bullets",
    items: [
      "自主海外注册：百济神州泽布替尼通过全球头对头III期（ALPINE研究）击败伊布替尼，获FDA批准CLL/SLL适应症，树立中国创新药自主出海标杆。",
      "对外授权（out-license）：国内Biotech将海外权益授权给跨国Pharma，由后者承担海外临床与商业化成本，本土企业获得首付款+里程碑+销售分成。",
      "联合开发（co-development）：传奇生物与强生共同开发西达基奥仑赛，共享全球收益，是中国细胞治疗出海的标杆案例。",
    ],
    sourceIds: ["S-DRUG-BEIGENE-2023-FILING", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "risk",
    items: [
      "海外临床失败风险：国内临床数据未必能直接外推到海外人群，头对头III期失败可能导致出海受挫。",
      "授权方履约风险：跨国Pharma可能因自身战略调整终止合作或延迟里程碑付款。",
      "地缘政治风险：美国《生物安全法案》等政策可能限制中国创新药在美注册与商业化。",
    ],
    sourceIds: ["S-DRUG-BEIGENE-2023-FILING", "S-DRONG-RCHANG-2023-FILING"],
  },
];
