import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "AI硬件板块呈现「代工龙头+芯片设计公司+终端品牌」三层格局。歌尔股份是全球可穿戴与AI眼镜代工龙头；瑞芯微、全志科技等凭借端侧AI芯片赋能终端；科大讯飞、小米等则打造自有品牌AI终端。",
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "bullets",
    items: [
      "歌尔股份：AI眼镜/AR眼镜、TWS耳机、智能手表代工全球龙头，深度绑定苹果、Meta、小米等头部客户（公司口径）。",
      "瑞芯微：RK3588系列赋能AIoT、AR眼镜、机器视觉，RV11系列赋能端侧AI视觉，技术领先（公司口径）。",
      "全志科技：R/A系列SoC在智能家居、机器人、AI音箱量产落地，端侧AI布局深化（公司口径）。",
      "科大讯飞：AI办公本、翻译机、智能录音笔等终端形成硬件+AI订阅商业模式（公司口径）。",
      "小米生态链：小米AI眼镜发售，生态链代工与元器件供应商受益（公司口径）。",
    ],
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "table",
    caption: "AI硬件核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["歌尔股份", "AI眼镜/可穿戴代工", "精密制造+头部客户", "多客户量产交付", "公司口径（年报披露）"],
      ["瑞芯微", "端侧AI芯片", "SoC生态+场景覆盖", "AIoT/AR眼镜放量", "公司口径（年报披露）"],
      ["全志科技", "端侧AI芯片", "IoT SoC客户基础", "智能家居/机器人量产", "公司口径（年报披露）"],
      ["科大讯飞", "AI终端", "AI能力+硬件协同", "订阅收入增长", "公司口径（年报披露）"],
      ["小米链", "AI眼镜/智能家居", "生态链+渠道+品牌", "AI眼镜发售", "产品发布+生态链"],
    ],
    sourceIds: ["S-AIHW-GOERTEK-FILING", "S-AIHW-RK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-IFLYTEK-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "risk",
    items: [
      "终端创新周期风险：AI眼镜等新品类渗透率可能低于预期，创新周期存在不确定性。",
      "客户集中风险：歌尔股份等代工厂商深度绑定少数头部客户，订单波动影响大。",
      "技术迭代风险：端侧AI芯片架构快速迭代，需持续跟进NPU算力与能效升级。",
      "供应链风险：芯片代工、光学模组等关键零部件供应链波动影响交付。",
    ],
    sourceIds: ["S-AIHW-IC-PLAN", "S-AIHW-EDGE-AI-TREND", "S-AIHW-GOERTEK-FILING"],
  },
];
