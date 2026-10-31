import { refreshAttemptLines } from "@/lib/dailyReviewRefreshAttempt";

/** Refresh attempt is distinct from the retained successful market observation. */
export function RefreshAttemptNotice({ attempt }: { attempt: unknown }) {
  const lines = refreshAttemptLines(attempt);
  if (!lines.length) return null;
  return <div className="my-2 rounded border border-border p-2 text-xs text-muted-foreground" aria-label="最近刷新尝试">
    {lines.map(line => <p key={line}>{line}</p>)}
  </div>;
}
