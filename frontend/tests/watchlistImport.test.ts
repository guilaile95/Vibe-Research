import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { previewWatchlistImport as preview, importPreviewCurrent, MAX_IMPORT_BYTES } from "../src/lib/watchlistImport.ts";

test("CSV selects identity columns only, preserves leading zeros and deduplicates", () => {
  const p = preview('名称,代码,市场,持仓数量\n"茅台,测试",600519,SH,999999\n五粮液,000858,SZ,555\n重复,000858,SZ,12\n北交,920001,BJ,1', ["600519"], "v1");
  assert.deepEqual(p.additions, ["000858", "920001"]);
  assert.deepEqual(p.rows.map(r => r.status), ["existing", "new", "duplicate", "new"]);
  assert.deepEqual(p.errors, []);
  assert.doesNotMatch(JSON.stringify(p), /999999|555|持仓|茅台/);
});
test("TSV, BOM, CRLF and explicit exchange aliases parse", () => {
  assert.deepEqual(preview('\uFEFFsymbol\texchange\r\n600519.SH\tSSE\r\nSZ000858\tXSHE\r\nBJ:430047\tBSE', [], null).additions, ["600519", "000858", "430047"]);
});
test("single column bare codes are permitted, never zero pad numeric coercions", () => {
  assert.deepEqual(preview("600519\n000858", [], null).additions, ["600519", "000858"]);
  for (const raw of ["858", "600519.0", "6.00519e5", "=600519", "AAPL", "00700", "HK:600519", "999999", "SH000858", "600519.SZ", "SZ600519.SH"]) {
    assert.equal(preview(raw, [], null).rows[0]?.status, "invalid", raw);
  }
});
test("conflicting or unsupported declared markets block entire apply", () => {
  for (const market of ["HK", "US", "SZ", "unknown"]) {
    const p = preview(`code,market\n600519,${market}\n000858,SZ`, [], "v");
    assert.equal(p.rows[0].status, "invalid"); assert.ok(p.errors.length);
  }
});
test("ambiguous columns, missing headers, malformed quote and row widths fail closed", () => {
  for (const raw of ['code,symbol\n600519,600519', 'code,market,exchange\n600519,SH,SH', '600519,99999', 'code,name\n600519', 'code,name\n600519,"unfinished', 'code,name\n600519,"x"bad']) assert.ok(preview(raw, [], null).errors.length, raw);
});
test("invalid row is visible and blocks partial import", () => {
  const p = preview('code\n600519\nwrong\n000858', [], null);
  assert.deepEqual(p.rows.map(r => r.status), ['new', 'invalid', 'new']);
  assert.ok(p.errors.length);
});
test("byte, row and merged watchlist bounds reject without truncation", () => {
  assert.ok(preview('汉'.repeat(MAX_IMPORT_BYTES / 2), [], null).errors.length);
  assert.ok(preview(Array(501).fill('600519').join('\n'), [], null).errors.length);
  const existing = Array.from({length:50}, (_,i) => String(600000+i));
  const p = preview('600519', existing, 'v'); assert.equal(p.next.length,51); assert.ok(p.errors.length);
});
test("preview cannot survive an authority version or content change", () => {
  const p = preview('600519', ['000858'], 'v');
  assert.equal(importPreviewCurrent(p,['000858'],'v'),true);
  assert.equal(importPreviewCurrent(p,['000858'],'v2'),false);
  assert.equal(importPreviewCurrent(p,['000001'],'v'),false);
});
test("component has explicit preview/apply and local file read, no upload or model endpoint", () => {
  const src = readFileSync(new URL('../src/components/watchlist/WatchlistImport.tsx',import.meta.url),'utf8');
  assert.match(src,/file\.text\(\)/); assert.match(src,/previewWatchlistImport\(text, codes, etag\)/);
  assert.match(src,/onApply\(preview.next\)/); assert.match(src,/applyingRef.current/);
  assert.doesNotMatch(src,/fetch\(|FormData|localStorage|api\./);
});
test("a tab inside a quoted CSV ignored column does not select TSV", () => {
  assert.deepEqual(preview('code,"name\tprivate"\n600519,"a\tb"', [], null).additions, ['600519']);
});
