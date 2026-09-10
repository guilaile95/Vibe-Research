import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { recoveredMarketApi } from "../src/lib/recoveredMarketApi.ts";
import type { PatternResult } from "../src/lib/recoveredMarketTypes.ts";

const originalFetch = globalThis.fetch;

const emptyResult = {
  schema_version: "research-data-plane.patterns.v0.1",
  dataset_id: "ashare_daily_unadjusted",
  provider_id: "local_bulk_dump",
  adjustment: "UNADJUSTED",
  status: "normal",
  fetched_at: null,
  requested_as_of: "2026-03-07",
  as_of: "2026-03-07",
  as_of_semantics: "ARTIFACT_DERIVED_LATEST_TRADE_DATE_AT_OR_BEFORE_REQUESTED_AS_OF",
  latest_date: "2026-03-07",
  source: null,
  artifact_identity: null,
  coverage: null,
  source_scope: null,
  pattern_registry: [],
  event_type_filter: "volume_surge",
  total_universe: 0,
  evaluable_count: 0,
  matched_stock_count: 0,
  not_evaluable_count: 0,
  not_evaluable_returned: 0,
  not_evaluable: [],
  events: [],
  returned_events: 0,
  total_events: 0,
  next_offset: null,
  formal_state_write: { performed: false, scope: "pattern discovery read-only" },
  limitations: [],
} satisfies PatternResult;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("getPatterns serializes latest/as_of, event filter, and bounded pagination", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = typeof input === "string" ? input : input.toString();
    return new Response(JSON.stringify(emptyResult), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  await recoveredMarketApi.getPatterns({
    latest: false,
    as_of: "2026-03-07",
    event_type: "volume_surge",
    limit: 50,
    offset: 20,
  });

  assert.equal(
    requestedUrl,
    "/api/research-data/patterns?as_of=2026-03-07&latest=false&event_type=volume_surge&limit=50&offset=20",
  );
});

test("Screener exposes Pattern Discovery as a same-level read-only mode", () => {
  const source = readFileSync(new URL("../src/pages/Screener.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.match(source, /data-testid="pattern-discovery-tab"/);
  assert.match(source, /data-testid="pattern-form"/);
  assert.match(source, /data-testid="pattern-results"/);
  assert.match(source, /data-testid="pattern-not-evaluable"/);
  assert.match(source, /不可评估（不是未触发）/);
  assert.match(source, /5\/20 日均量比超过 2\.0/);
  assert.doesNotMatch(source, /5\/20 日均量比达到 2\.0/);
  assert.match(source, /candidateWorkspaceHref\(event\.code\)/);
});

test("Pattern mode clears stale results and guards late responses", () => {
  const source = readFileSync(new URL("../src/pages/Screener.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.match(source, /setPatternResult\(null\);\n\s*setLoading\(true\);/);
  assert.match(source, /if \(!controller\.signal\.aborted && controllerRef\.current === controller\) \{/);
  assert.match(source, /if \(controllerRef\.current === controller\) \{\n\s*controllerRef\.current = null;\n\s*setLoading\(false\);/);
  assert.match(source, /不可评估不等于未触发/);
});
