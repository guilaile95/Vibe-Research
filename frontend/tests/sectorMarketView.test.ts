import assert from "node:assert/strict";
import test from "node:test";

import { formatActivity, formatSectorPercent, mappedSectorRows } from "../src/lib/sectorMarketView.ts";

test("sector market formatting preserves missing values and signed observations", () => {
  assert.equal(formatSectorPercent(null), "—");
  assert.equal(formatSectorPercent(0), "0.00%");
  assert.equal(formatSectorPercent(1.234), "+1.23%");
  assert.equal(formatSectorPercent(-2.345), "-2.35%");
  assert.equal(formatActivity(null), "—");
  assert.equal(formatActivity(1.257), "1.26×");
});

test("sector matrix keeps only explicit mappings and uses backend rank", () => {
  const rows = mappedSectorRows([
    { sector_key: "b", mapping_status: "mapped", rank_20d_within_mapped: 2 },
    { sector_key: "x", mapping_status: "unavailable", rank_20d_within_mapped: null },
    { sector_key: "a", mapping_status: "mapped", rank_20d_within_mapped: 1 },
  ] as never);
  assert.deepEqual(rows.map((row) => row.sector_key), ["a", "b"]);
});
