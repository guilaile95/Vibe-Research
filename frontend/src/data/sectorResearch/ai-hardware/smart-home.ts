import type { ContentBlock } from "../types.ts";

export const smartHomeBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能家居终端正从「联网控制」向「AI原生交互」升级。大模型接入智能音箱、智能摄像头、智能家电等终端，实现自然语言理解、多轮对话与主动服务。AI音箱、AI摄像头、AI玩具等是率先落地的品类。",
    sourceIds: ["S-AIHW-IFLYTEK-FILING", "S-AIHW-ALLWINNER-FILING"],
  },
  {
    type: "table",
    caption: "AI智能家居终端品类与代表厂商",
    headers: ["品类", "核心AI功能", "市场渗透率", "代表A股厂商"],
    rows: [
      ["AI音箱", "语音助手/智能家居控制/教育", "较高", "科大讯飞、百度、小米"],
      ["AI摄像头", "人形检测/异常行为识别/语音对讲", "中等", "海康威视、大华股份"],
      ["AI家电", "智能空调/冰箱/洗衣机语音交互", "成长中", "美的、海尔、格力"],
      ["AI玩具", "儿童教育/情感陪伴/互动游戏", "早期", "全志科技、乐鑫科技"],
      ["扫地机器人", "路径规划/避障/语音控制", "成长中", "科沃斯、石头科技"],
    ],
    sourceIds: ["S-AIHW-IFLYTEK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "bullets",
    items: [
      "科大讯飞：AI办公本、翻译机、智能录音笔等终端实现硬件+AI订阅商业模式（公司口径）。",
      "全志科技：SoC赋能AI玩具、AI音箱、智能家居等终端智能化（公司口径）。",
      "扫地机器人：科沃斯与石头科技通过AI视觉与算法升级产品力，国内市场份额领先。",
      "多模态交互：语音+视觉+手势多模态AI交互成为智能家居终端新趋势。",
    ],
    sourceIds: ["S-AIHW-IFLYTEK-FILING", "S-AIHW-ALLWINNER-FILING", "S-AIHW-XIAOMI-SUPPLYCHAIN"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1) 智能家居AI交互体验的实际用户粘性；2) AI玩具与AI家电的市场渗透率拐点；3) 智能家居AI标准与互联互通进展。",
    sourceIds: ["S-AIHW-IC-PLAN", "S-AIHW-EDGE-AI-TREND"],
  },
];
