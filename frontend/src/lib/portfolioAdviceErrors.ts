// 持仓建议错误文案映射（纯函数，供页面 store 与离线单测复用；不依赖路径别名）。

type StatusError = {
  status: number;
  message?: string;
};

function asStatusError(error: unknown): StatusError | null {
  if (!error || typeof error !== "object") return null;
  const status = (error as { status?: unknown }).status;
  if (typeof status !== "number") return null;
  const message = (error as { message?: unknown }).message;
  return {
    status,
    message: typeof message === "string" ? message : undefined,
  };
}

/** 后端 502 公开文案白名单：透传；未知 502 文案仍回退通用失败，避免把上游 body 直接刷屏。 */
const PORTFOLIO_ADVICE_502_MESSAGES = new Set([
  "持仓建议模型调用失败",
  "持仓建议模型输出无效",
  "持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI",
  "持仓建议模型网络调用失败，请检查网络后重试",
  "持仓建议模型配置无效，请检查 Base URL 与模型名",
  "未检测到本机 CLI，请先安装并登录，或改用 API 接入",
  "持仓建议 CLI 调用失败，请确认已登录对应 CLI 后重试",
]);

export function getPortfolioAdviceErrorMessage(error: unknown): string {
  const apiErr = asStatusError(error);
  if (!apiErr) return "持仓建议生成失败，请重试";
  if (apiErr.status === 409) return apiErr.message || "当前没有持仓，无法生成持仓操作建议";
  if (apiErr.status === 503) {
    return apiErr.message || "市场核心数据暂不可用，无法生成可靠的持仓操作建议";
  }
  if (apiErr.status === 502) {
    const msg = (apiErr.message || "").trim();
    if (PORTFOLIO_ADVICE_502_MESSAGES.has(msg)) return msg;
    // 兼容「未检测到「xxx」对应的本机命令…」等后端动态但安全的 CLI 文案
    if (msg.includes("未检测到") && (msg.includes("CLI") || msg.includes("本机命令"))) {
      return msg;
    }
    return "持仓建议生成失败，请重试";
  }
  if (apiErr.status === 500) return apiErr.message || "持仓操作建议生成失败";
  if (apiErr.status === 400) {
    const msg = (apiErr.message || "").trim();
    // 后端已对缺 model / 缺 key / 未装 CLI 返回明确文案；空消息时给默认引导
    return msg || "请先在“接入 AI”中配置模型";
  }
  return apiErr.message || "持仓建议生成失败，请重试";
}
