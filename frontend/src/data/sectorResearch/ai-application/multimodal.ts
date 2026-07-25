import type { ContentBlock } from "../types.ts";

export const multimodalBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "多模态大模型是AI应用进化的核心方向，实现文本/图像/视频/音频的统一理解与生成。文生图、文生视频、语音克隆等AIGC应用加速商业化，AI音乐、AI社交等创新场景持续涌现。",
    sourceIds: ["S-AIAPP-KUNLUN-FILING", "S-AIAPP-IFLYTEK-FILING"],
  },
  {
    type: "table",
    caption: "多模态AI能力矩阵与代表产品",
    headers: ["多模态能力", "核心功能", "应用场景", "代表厂商/产品"],
    rows: [
      ["文生图", "文本描述生成图片", "设计/营销/游戏", "Stable Diffusion、Midjourney、通义万相"],
      ["文生视频", "文本描述生成视频", "短视频/广告/影视", "Sora、可灵、即梦"],
      ["语音合成", "文本转自然语音", "客服/导航/有声书", "讯飞语音、Azure TTS"],
      ["AI音乐", "歌词/风格生成音乐", "内容创作/背景音乐", "昆仑万维Mureka、Suno"],
      ["数字人", "多模态交互虚拟形象", "直播/客服/教育", "科大讯飞、万兴科技"],
    ],
    sourceIds: ["S-AIAPP-KUNLUN-FILING", "S-AIAPP-IFLYTEK-FILING"],
  },
  {
    type: "bullets",
    items: [
      "昆仑万维：AI音乐Mureka、AI社交Opera AI等矩阵，海外AIGC应用商业化领先（公司口径）。",
      "文生视频：Sora引领长视频生成，国内可灵、即梦、海螺等快速跟进，短视频与影视制作场景率先落地。",
      "多模态Agent：视觉理解+语音交互+工具调用的多模态Agent成为下一代人机交互入口。",
      "合规风险：AIGC内容版权、深度伪造(Deepfake)与内容安全监管趋严。",
    ],
    sourceIds: ["S-AIAPP-KUNLUN-FILING", "S-AIAPP-GENERATIVE-AI-SERVICE"],
  },
];
