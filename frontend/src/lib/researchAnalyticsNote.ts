import { analyticsModes, parseAnalyticsReport, type AnalyticsMode, type AnalyticsReport } from "./researchAnalytics.ts";

/** Explicit local note, never an input archive or a claim of historical availability. */
export function researchAnalyticsNote(report: AnalyticsReport, mode: AnalyticsMode, synthetic: boolean) {
  if (typeof synthetic !== "boolean") throw new Error("结果来源标记不可核对");
  const validated = parseAnalyticsReport(report, mode);
  const label = analyticsModes.find(item => item.id === mode)?.label;
  if (!label) throw new Error("结果类型不可核对");
  const serialized = JSON.stringify(validated, null, 2);
  if (new TextEncoder().encode(serialized).length > 1024 * 1024) throw new Error("结果超过1MiB本地记录上限，未保存；请缩小研究窗口");
  return {
    kind: mode === "simulation" ? "回测研究" : "研究计算",
    title: `${label} · ${validated.input_fingerprint.slice(0, 16)}`,
    content: `# ${label}\n\n只读研究计算结果，事实及历史可得性未证明。\n\n结果状态：${validated.status}\n\n输入指纹：${validated.input_fingerprint}\n\n材料标记：${synthetic ? "合成示例或编辑后的示例；不代表真实市场证据" : "用户显式输入；真实性未核验"}\n\n仅保存本次结果与指纹，未保存原始输入。若结果包含账本投影，它仍只保存在当前浏览器；进一步发送模型前需自行核对。\n\n\`\`\`json\n${serialized}\n\`\`\``,
  };
}
