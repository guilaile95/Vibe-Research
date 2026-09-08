import assert from "node:assert/strict";
import test from "node:test";

const requests: Array<{ url: string; method: string; body: BodyInit | null | undefined; signal?: AbortSignal }> = [];
const storage = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  },
});

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  requests.push({
    url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
    method: init?.method ?? "GET",
    body: init?.body,
    signal: init?.signal,
  });
  return new Response(JSON.stringify({ data: {
    schema_version: "research_event_calendar.v0.1",
    status: "NORMAL",
    events: [],
  } }), { status: 200, headers: { "Content-Type": "application/json" } });
}) as typeof fetch;

const { api } = await import("../src/lib/api.ts");

test("research event calendar API is bounded GET with repeated filters and no body", async () => {
  requests.length = 0;
  const result = await api.getResearchEventCalendar({
    date_from: "2026-09-01",
    date_to: "2026-09-30",
    event_types: ["ANNOUNCEMENT", "LOCKUP_EXPIRY"],
    campaign_ids: ["campaign_" + "a".repeat(32)],
  });
  const request = requests.at(-1);
  assert.ok(request);
  assert.equal(request.method, "GET");
  assert.equal(request.body, undefined);
  assert.match(request.url, /\/api\/research-events\?/);
  assert.match(request.url, /event_types=ANNOUNCEMENT/);
  assert.match(request.url, /event_types=LOCKUP_EXPIRY/);
  assert.match(request.url, /campaign_ids=campaign_/);
  assert.equal(result.schema_version, "research_event_calendar.v0.1");
});

test("research event calendar API forwards AbortSignal without changing the read method", async () => {
  requests.length = 0;
  const controller = new AbortController();
  await api.getResearchEventCalendar({ signal: controller.signal });
  const request = requests.at(-1);
  assert.ok(request);
  assert.equal(request.method, "GET");
  assert.equal(request.signal, controller.signal);
});
