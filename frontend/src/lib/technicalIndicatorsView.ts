/** 技术指标与价格触发展示纯函数（可单测，无 React，永不抛异常）。 */

export type IndicatorStatus = "normal" | "partial" | "unavailable";

/** 价格 / 指标类数值格式化：保留 2 位小数；null / NaN → "—"，禁止 "0" / "0.00"。 */
export function formatPrice(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

/** 通用指标格式化：保留 digits 位小数；null / NaN → "—"。 */
export function formatIndicator(v: number | null | undefined, digits = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

/** 量比格式化：保留 2 位 + `x` 后缀（如 `2.35x`）；null / NaN → "—"。 */
export function formatVolumeRatio(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v.toFixed(2)}x`;
}

/** RSI 区间标签：≥70 高位 / ≤30 低位 / 之间 中性 / null 返回 "—"（中性色）。 */
export function rsiZoneLabel(rsi: number | null | undefined): { text: string; cls: string } {
  if (typeof rsi !== "number" || !Number.isFinite(rsi)) {
    return { text: "—", cls: "text-muted-foreground" };
  }
  if (rsi >= 70) return { text: "高位区间", cls: "border-danger/40 bg-danger/10 text-danger border" };
  if (rsi <= 30) return { text: "低位区间", cls: "border-success/40 bg-success/10 text-success border" };
  return { text: "中性区间", cls: "border-border/60 bg-muted/30 text-muted-foreground border" };
}

/** 三态状态徽标（照抄仓库既有 tri-state 映射：emerald / amber / muted）。 */
export function indicatorStatusLabel(
  status: IndicatorStatus | string | null | undefined,
): { text: string; cls: string } {
  if (status === "normal") {
    return {
      text: "正常",
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border",
    };
  }
  if (status === "partial") {
    return {
      text: "部分可用",
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400 border",
    };
  }
  return {
    text: "不可用",
    cls: "border-border/60 bg-muted/30 text-muted-foreground border",
  };
}

/** 触发事实 → 人类可读行（中性事实描述，不做买卖建议）。 */
export function triggerLines(
  triggers: Array<{ type: string; message: string; value: number | null }> | null | undefined,
): string[] {
  if (!Array.isArray(triggers)) return [];
  return triggers.map((t) => {
    if (!t) return "";
    const msg = (t.message ?? "").trim();
    return msg;
  }).filter(Boolean);
}

/** limitation 列表 → 人类可读行。 */
export function limitationLines(
  env: { limitations?: Array<{ field?: string; reason_code?: string; detail?: string } | null> | null } | null | undefined,
): string[] {
  if (!env?.limitations || !Array.isArray(env.limitations)) return [];
  return env.limitations.map((lim) => {
    if (!lim) return "";
    const field = (lim.field ?? "").trim();
    const detail = (lim.detail ?? "").trim();
    if (field && detail) return `${field}: ${detail}`;
    return field || detail || "";
  }).filter(Boolean);
}

/** 错误态文案：status===0 后端连接不可用，501 依赖未就绪，其余通用兜底。 */
export function indicatorErrorMessage(status: number | undefined): string {
  if (status === 0) return "后端连接不可用";
  if (status === 501) return "依赖未就绪";
  return "技术指标暂不可用";
}
