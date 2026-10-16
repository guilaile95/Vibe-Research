/** Limits apply to the model phase; subscription cost cannot be measured here. */
export function AiTaskBudgetNotice({ task, rounds = 1 }: { task: "daily" | "debate"; rounds?: number }) {
  const calls = task === "daily" ? 1 : rounds >= 2 ? 5 : 3;
  return (
    <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground/70" data-testid="ai-task-budget-notice">
      模型阶段的本地等待预算为 {task === "daily" ? 90 : 180} 秒，{task === "daily" ? "复盘数据准备" : "底稿采集"}时间另计。
      API 最多 {calls} 次请求，每次请求限制输出 2500 token；本地累计输出上限 {calls * 12000} 字符。
      Codex Subscription 最多 {calls} 次运行时调用，限制本地等待与输出，不能限制或核验服务端模型调用、token 或费用。
      超限或中止会请求关闭连接／取消，远端停止与清理完成时间无法保证；不自动重试，未完成内容不能保存为完整结果。
      实际费用未知，不代表免费，请以提供方账单或订阅额度为准。
    </p>
  );
}
