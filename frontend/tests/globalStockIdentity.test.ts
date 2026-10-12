import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { api, ApiError } from "../src/lib/api.ts";

for (const method of ["globalStock", "hkCashflow"] as const) {
  for (const [status, detail] of [
    [400, "证券标识存在歧义，请核对并输入准确代码及适用的市场后缀。"],
    [404, "未找到代码"],
    [503, "证券搜索接口暂时不可用，请稍后重试；这与「查无此代码」不同。"],
  ] as const) {
    test(`${method}: ${status} is an actionable error, never a stock payload`, async (t) => {
      const calls: string[] = [];
      t.mock.method(globalThis, "fetch", async (url: string | URL | Request) => {
        calls.push(String(url));
        return new Response(JSON.stringify({ detail }), { status });
      });
      await assert.rejects(api[method]("005930.KS"), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.equal(error.message, detail);
        return true;
      });
      assert.equal(calls.length, 1, "no client fallback or alternate-security request");
      assert.ok(calls[0]!.endsWith("symbol=005930.KS"));
    });
  }
}

test("StockData's existing global query sink clears prior stock, guards late responses, and renders API errors", () => {
  const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  const run = source.slice(source.indexOf("const run = useCallback"), source.indexOf("const submitQuery"));
  assert.match(run, /setGStock\(null\)/);
  assert.match(run, /if \(!\/\^\\d\{6\}\$\/\.test\(c\)\)/);
  assert.match(run, /if \(rid === runIdRef.current\) setGStock\(g\)/);
  assert.match(run, /if \(rid === runIdRef.current\) setErr\(e instanceof ApiError \? e.message/);
  assert.match(source, /\{err && \([\s\S]*?<AlertCircle[^>]*\/> \{err\}/);
});
