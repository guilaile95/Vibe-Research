import assert from "node:assert/strict";
import test from "node:test";

import { getDailyReviewAiRestoreTradeDate } from "../src/stores/dailyReviewAiResultMetadata.ts";

test("daily review generation rereads the authoritative committed trade date from done result", () => {
  const result = getDailyReviewAiRestoreTradeDate({
    result_type: "daily_review_ai",
    trade_date: "2026-07-23",
    schema_version: "daily_review_ai.v1",
    generated_at: "2026-07-23 16:02:15",
  });

  const pageTradeDate = "2026-07-22";
  const finalRestoreTradeDate = result;

  assert.equal(pageTradeDate, "2026-07-22");
  assert.equal(finalRestoreTradeDate, "2026-07-23");
});

test("daily review generation fails when done result metadata is absent or invalid", () => {
  assert.equal(getDailyReviewAiRestoreTradeDate(undefined), null);
  assert.equal(
    getDailyReviewAiRestoreTradeDate({
      result_type: "daily_review_ai",
      trade_date: "2026-07-23",
      schema_version: "daily_review_ai.v1",
      generated_at: "2026-07-23T16:02:15",
    }),
    null,
  );
});
