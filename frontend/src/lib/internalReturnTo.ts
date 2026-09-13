/** Display-only back-chip labels for in-app return_to paths. */
export function evidenceReturnToLabel(returnTo: string): string {
  if (returnTo.startsWith("/candidates/")) return "候选研究";
  if (returnTo.startsWith("/thesis")) return "投资逻辑";
  if (returnTo.startsWith("/stock-data")) return "个股数据";
  return returnTo ? "返回" : "证据库";
}
