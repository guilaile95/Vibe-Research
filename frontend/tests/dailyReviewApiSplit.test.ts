import assert from "node:assert/strict";
import test from "node:test";

import { createDailyReviewClient } from "../src/lib/api/dailyReview.ts";
import type { DailyReviewData } from "../src/lib/api/types/dailyReview.ts";

test("daily review client keeps history and stream request contracts independent from the api facade", async () => {
  const getPaths: string[] = [];
  const streamCalls: Array<{ path: string; body: unknown }> = [];
  const client = createDailyReviewClient({
    get: async <T>(path: string) => {
      getPaths.push(path);
      return {} as T;
    },
    request: async <T>() => ({} as T),
    authHeaders: () => ({}),
    createApiError: (message) => new Error(message),
    streamNdjson: async (path, body) => {
      streamCalls.push({ path, body });
      return { content: "", trace: [], rounds: 0 };
    },
  });

  await client.listHistory({ trade_date: "2026-08-08", limit: 20, offset: 40 });
  await client.compareHistory({ base_id: 1, target_id: 2, board_limit: 5, stock_limit: 10 });
  await client.analyzeStream({ user_request: null, llm: { provider: "test", baseURL: "", apiKey: "", model: "test" } });

  assert.deepEqual(getPaths, [
    "/daily-review/history?trade_date=2026-08-08&limit=20&offset=40",
    "/daily-review/history/compare?base_id=1&target_id=2&board_limit=5&stock_limit=10",
  ]);
  assert.deepEqual(streamCalls, [{
    path: "/daily-review/analyze",
    body: { user_request: null, llm: { provider: "test", baseURL: "", apiKey: "", model: "test" } },
  }]);
});

test("daily review types remain available from the legacy api type barrel", async () => {
  const legacy = await import("../src/lib/api/types.ts");
  const sample: import("../src/lib/api/types.ts").DailyReviewData = {
    schema_version: "v1", generated_at: "now", trade_date: null, data_cutoff: null,
  } as DailyReviewData;

  assert.equal(typeof legacy, "object");
  assert.equal(sample.schema_version, "v1");
});
