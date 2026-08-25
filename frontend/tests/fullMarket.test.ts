import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { recoveredMarketApi } from "../src/lib/recoveredMarketApi.ts";
import type { FullMarketResult } from "../src/lib/recoveredMarketTypes.ts";
import {
  buildFullMarketQuery,
  formatFullMarketMetric,
} from "../src/lib/recoveredScreener.ts";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("Full Market query defaults and explicit as_of validation", () => {
  assert.deepEqual(buildFullMarketQuery({}), {
    latest: true,
    sort_by: "code",
    sort_order: "asc",
    limit: 50,
    offset: 0,
  });
  assert.throws(
    () => buildFullMarketQuery({ latest: false }),
    /latest=false.*as_of/,
  );
  assert.throws(
    () => buildFullMarketQuery({ filter_metric: "return_20d", filter_operator: "gte" }),
    /全市场筛选参数无效/,
  );
  assert.deepEqual(
    buildFullMarketQuery({
      latest: false,
      as_of: "2026-02-20",
      filter_metric: "return_20d",
      filter_operator: "gte",
      filter_value: 0.05,
      sort_by: "latest_close",
      sort_order: "desc",
    }),
    {
      latest: false,
      as_of: "2026-02-20",
      filter_metric: "return_20d",
      filter_operator: "gte",
      filter_value: 0.05,
      sort_by: "latest_close",
      sort_order: "desc",
      limit: 50,
      offset: 0,
    },
  );
});

test("Full Market metric formatting preserves unknowns", () => {
  assert.equal(formatFullMarketMetric("return_20d", 0.1234), "12.34%");
  assert.equal(formatFullMarketMetric("volume_ratio_20d", 1.5), "1.50x");
  assert.equal(formatFullMarketMetric("latest_close", null), "不可评估");
  assert.equal(formatFullMarketMetric("latest_close", "not-a-number"), "不可评估");
});

test("Screener clears stale Full Market results and settles loading after abort", () => {
  const source = readFileSync(new URL("../src/pages/Screener.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.match(source, /setFullMarketResult\(null\);\n\s*setLoading\(true\);/);
  assert.match(source, /if \(controllerRef\.current === controller\) \{\n\s*controllerRef\.current = null;\n\s*setLoading\(false\);/);
  assert.match(source, /controllerRef\.current = null;\n\s*setLoading\(false\);\n\s*setFullMarketResult\(null\);/);
  assert.match(source, /if \(controller\.signal\.aborted\) return;/);
});

test("getFullMarket serializes the ordinary Screener wrapper query", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = typeof input === "string" ? input : input.toString();
    const body: FullMarketResult = {
      schema_version: "research-data-plane.full-market.v0.1",
      dataset_id: "ashare_daily_unadjusted",
      provider_id: "local_bulk_dump",
      adjustment: "UNADJUSTED",
      status: "normal",
      fetched_at: null,
      as_of: "2026-02-20",
      latest_date: "2026-02-20",
      coverage: null,
      provenance: { source_kind: null, source_name: null, artifact_sha256: null, license_status: null },
      breadth: {
        ma20: { breadth: null, above_count: 0, evaluable_count: 0, insufficient_count: 0, status: "INSUFFICIENT_HISTORY" },
        ma60: { breadth: null, above_count: 0, evaluable_count: 0, insufficient_count: 0, status: "INSUFFICIENT_HISTORY" },
      },
      rows: [],
      returned_rows: 0,
      total_rows: 0,
      next_offset: null,
      limitations: [],
    };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  await recoveredMarketApi.getFullMarket({
    latest: false,
    as_of: "2026-02-20",
    filter_metric: "return_20d",
    filter_operator: "gte",
    filter_value: 0.05,
    sort_by: "latest_close",
    sort_order: "desc",
    limit: 10,
    offset: 20,
  });

  assert.equal(
    requestedUrl,
    "/api/screener/full-market?as_of=2026-02-20&latest=false&filter_metric=return_20d&filter_operator=gte&filter_value=0.05&sort_by=latest_close&sort_order=desc&limit=10&offset=20",
  );
});
