export interface DailyReviewAiPersistedResultMetadata {
  result_type: "daily_review_ai" | "portfolio_advice";
  trade_date: string;
  schema_version: string;
  generated_at: string;
}

const TRADE_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const GENERATED_AT_RE = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

export function getDailyReviewAiRestoreTradeDate(
  result: DailyReviewAiPersistedResultMetadata | null | undefined,
): string | null {
  if (
    !result
    || result.result_type !== "daily_review_ai"
    || result.schema_version !== "daily_review_ai.v1"
    || !TRADE_DATE_RE.test(result.trade_date)
    || !GENERATED_AT_RE.test(result.generated_at)
  ) {
    return null;
  }
  return result.trade_date;
}
