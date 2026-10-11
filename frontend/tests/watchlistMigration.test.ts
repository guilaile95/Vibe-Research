import assert from "node:assert/strict";
import test from "node:test";

import { migrateLocalWatchlistOnce } from "../src/lib/watchlist.ts";

for (const status of [400, 409, 502, 200]) {
  test(`local draft is cleared only after successful import (HTTP ${status})`, async (t) => {
    const codes = Array.from({ length: status === 400 ? 51 : 2 }, (_, i) => String(600000 + i));
    const draft = JSON.stringify(codes);
    const values = new Map([["vr-watchlist", draft]]);
    const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        removeItem: (key: string) => values.delete(key),
      },
    });
    t.after(() => {
      if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
      else Reflect.deleteProperty(globalThis, "localStorage");
    });
    let requests = 0;
    t.mock.method(globalThis, "fetch", async (url: unknown, init: RequestInit) => {
      requests++;
      assert.equal(String(url), "/api/watchlist/import-local");
      assert.equal(init.method, "POST");
      assert.deepEqual(JSON.parse(String(init.body)), { codes, expected_etag: "current" });
      return new Response(JSON.stringify(status === 200
        ? { data: { codes, added: codes, etag: "saved", updated_at: "test" } }
        : { detail: "Import rejected" }), { status });
    });
    if (status === 200) {
      const result = await migrateLocalWatchlistOnce("current");
      assert.deepEqual(result.codes, codes);
      assert.equal(result.migrated, true);
      assert.equal(values.has("vr-watchlist"), false);
    } else {
      await assert.rejects(migrateLocalWatchlistOnce("current"));
      assert.equal(values.get("vr-watchlist"), draft);
    }
    assert.equal(requests, 1);
  });
}

test("authoritative load exposes a rejected migration while retaining both sources", async (t) => {
  const draft = JSON.stringify(Array.from({ length: 51 }, (_, i) => String(600000 + i)));
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: () => draft,
    removeItem: () => assert.fail("rejected import must preserve draft"),
  } });
  t.after(() => {
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
  const requests: string[] = [];
  t.mock.method(globalThis, "fetch", async (url: unknown) => {
    requests.push(String(url));
    if (String(url) === "/api/watchlist") return new Response(JSON.stringify({ data: {
      status: "valid", data: { codes: ["600000"], updated_at: "test" }, etag: "current",
    } }));
    assert.equal(String(url), "/api/watchlist/import-local");
    return new Response(JSON.stringify({ detail: "关注股超过上限 50（去重后 51 只）" }), { status: 400 });
  });
  const { loadWatchAuthoritative } = await import("../src/lib/watchlist.ts");
  const result = await loadWatchAuthoritative();
  assert.deepEqual(result.codes, ["600000"]);
  assert.equal(result.migrated, false);
  assert.match(result.migrationError ?? "", /超过上限 50/);
  assert.deepEqual(requests, ["/api/watchlist", "/api/watchlist/import-local"]);
});
