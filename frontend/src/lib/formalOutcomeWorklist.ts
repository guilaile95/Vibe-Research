import type {
  FormalDecisionOutcome,
  FormalDecisionReviewWorklist,
  FormalReviewWorklistItem,
} from "@/lib/api/types";

export type FormalReviewWorklistFilter = "due" | "upcoming" | "unavailable";

export function worklistItems(
  worklist: FormalDecisionReviewWorklist,
  filter: FormalReviewWorklistFilter,
): readonly FormalReviewWorklistItem[] {
  return worklist[filter];
}

export function worklistLabel(filter: FormalReviewWorklistFilter): string {
  if (filter === "due") return "Review due";
  if (filter === "upcoming") return "Upcoming";
  return "Authority unavailable";
}

export function mergeOutcomeItem(
  items: readonly FormalDecisionOutcome[],
  outcome: FormalDecisionOutcome,
): FormalDecisionOutcome[] {
  const index = items.findIndex((item) => item.decision_id === outcome.decision_id);
  if (index < 0) return [...items, outcome];
  return items.map((item, currentIndex) => currentIndex === index ? outcome : item);
}
