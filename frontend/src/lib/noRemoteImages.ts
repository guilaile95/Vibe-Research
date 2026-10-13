import { createElement } from "react";
import type { Components } from "react-markdown";

/**
 * Adapted from simonlin1212/Vibe-Research, MIT (see root LICENSE):
 * https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/desktop/src/core/ai/noRemoteImages.tsx
 *
 * AI, report and imported-note Markdown is untrusted text. Never turn its image
 * syntax into automatic resource requests, including relative/local URLs.
 * Keep readable alt text without retaining src/title or changing saved content.
 * This override does not apply to intentional images in trusted app components.
 */
export const noRemoteImages: Components = {
  img: ({ alt }) => createElement(
    "span",
    { className: "text-muted-foreground" },
    `[图片未加载：${alt || "图片"}]`,
  ),
};
