import test from "node:test";
import assert from "node:assert/strict";
import { stockDebateHref, stockDebateHrefForResult, debateCodeFromSearch } from "../src/lib/debateHandoff.ts";
test("returned A identity and leading zeros survive explicit navigation", () => {
  assert.equal(stockDebateHrefForResult("000001", {code:"000001"}, null), "/debate?code=000001");
  assert.equal(debateCodeFromSearch("?code=000001"), "000001");
});
test("missing, stale and global results cannot become an A handoff", () => {
  assert.equal(stockDebateHrefForResult("000001", null, null), null);
  assert.equal(stockDebateHrefForResult("000001", {code:"600519"}, null), null);
  assert.equal(stockDebateHrefForResult("000001", {code:"000001"}, {market:"HK",code:"000001"}), null);
  assert.equal(stockDebateHrefForResult("AAPL", {code:"AAPL"}, null), null);
});
test("ambiguous query and invalid code remain blank", () => {
  for (const value of ["?code=000001&code=600519", "?code=AAPL", "?code=123", "?code=%20"]) assert.equal(debateCodeFromSearch(value),"");
  for (const value of [null, 1, "000001&token=x", "000001 "]) assert.equal(stockDebateHref(value), null);
});
