import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { recoveredMarketApi } from "../src/lib/recoveredMarketApi.ts";
import type { DragonTigerDiscovery } from "../src/lib/recoveredMarketTypes.ts";

const originalFetch = globalThis.fetch;

const fixture: DragonTigerDiscovery = {
  schema_version: "dragon_tiger_discovery.v0.1",
  provider: "EASTMONEY_DATA_CENTER",
  report_name: "RPT_DAILYBILLBOARD_DETAILSNEW",
  source: {
    provider: "EASTMONEY_DATA_CENTER",
    report_name: "RPT_DAILYBILLBOARD_DETAILSNEW",
    query_scope: "MARKET_LEVEL_WITHOUT_SECURITY_CODE_FILTER",
    date_semantics: "SOURCE_PROVIDED_TRADE_DATE",
    billboard_net_amount_semantics: "BILLBOARD_BUY_AMT_MINUS_BILLBOARD_SELL_AMT",
  },
  status: "NORMAL",
  trade_date: "2026-09-09",
  requested_trade_date: null,
  date_semantics: "SOURCE_PROVIDED_TRADE_DATE",
  fetched_at: "2026-09-09T00:00:00Z",
  pagination: {
    page_size: 50,
    max_pages: 4,
    max_rows: 200,
    fetched_pages: 2,
    source_count: 66,
    source_pages: 2,
    returned_rows: 2,
    truncated: false,
  },
  completeness: { status: "COMPLETE", source_count: 66, returned_rows: 2, truncated: false, malformed_rows: 0 },
  rows: [{
    trade_date: "2026-09-09",
    security_code: "000001",
    security_name: "测试标的",
    reason: "公开上榜原因",
    billboard_net_amount: 0,
    billboard_net_amount_unit: "YUAN",
    turnover_rate_pct: null,
    source_record_identity: "TRADE_ID:test",
  }],
  limitations: [],
  formal_state_write: { performed: false, scope: "read-only market discovery" },
};

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("Dragon-Tiger API keeps latest and explicit source-date query shapes", async () => {
  const requestedUrls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrls.push(typeof input === "string" ? input : input.toString());
    return new Response(JSON.stringify(fixture), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  await recoveredMarketApi.getDragonTigerDiscovery();
  await recoveredMarketApi.getDragonTigerDiscovery("2026-09-08");

  assert.equal(requestedUrls[0], "/api/market/dragon-tiger");
  assert.equal(requestedUrls[1], "/api/market/dragon-tiger?trade_date=2026-09-08");
});

test("Dragon-Tiger panel exposes source boundary and allowed research links", () => {
  const source = readFileSync(new URL("../src/components/discovery/DragonTigerDiscoveryPanel.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.match(source, /不是全 A 股票清单/);
  assert.match(source, /不产生买卖建议/);
  assert.match(source, /stock-data\?code=/);
  assert.match(source, /candidateWorkspaceHref/);
  assert.doesNotMatch(source, /BUY|SELL|买入建议|卖出建议/);
});
