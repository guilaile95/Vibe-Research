import type {
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
