import assert from "node:assert/strict";
import test from "node:test";
import { clearResearchVisits, loadResearchVisits, parseResearchVisits, rememberResearchVisit, researchVisitHref } from "../src/lib/researchResume.ts";

test("resume keeps validated discovery return and section, never arbitrary candidate metadata", () => {
  const source = "/screener?mode=discovery&strategy=SWING&industry=白酒#opportunity-600519";
  const path = `/candidates/600519?${new URLSearchParams({ source: "discovery", strategy: "SWING", return_to: source, claim: "unsupported" })}#candidate-evidence-gap`;
  const result = new URL(researchVisitHref(path)!, "http://localhost");
  assert.equal(new URL(result.searchParams.get("return_to")!, "http://localhost").searchParams.get("industry"), "白酒");
  assert.equal(new URL(result.searchParams.get("return_to")!, "http://localhost").hash, "#opportunity-600519");
  assert.equal(result.searchParams.get("strategy"), "SWING");
  assert.equal(result.searchParams.get("claim"), null);
  assert.equal(result.hash, "#candidate-evidence-gap");
  assert.equal(researchVisitHref("/candidates/000001?return_to=https://outside.example#unknown"), "/candidates/000001");
  for (const path of ["//outside.example/candidates/600519", "https://outside.example/candidates/600519", "/candidates/abc", "/evidence/new", "/candidates/600519/extra"]) assert.equal(researchVisitHref(path), null);
});

test("browser history is bounded, replaces same security and can be cleared without touching other storage", () => {
  const state = new Map([["other-key", "preserved"]]);
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => state.get(key) ?? null,
    setItem: (key: string, value: string) => state.set(key, value),
    removeItem: (key: string) => state.delete(key),
  } });
  try {
    for (const code of ["000001", "600519", "000858", "300750"]) rememberResearchVisit(`/candidates/${code}`);
    rememberResearchVisit("/candidates/600519#candidate-existing-research");
    assert.deepEqual(loadResearchVisits().map((v) => v.code), ["600519", "300750", "000858"]);
    assert.equal(loadResearchVisits()[0].href, "/candidates/600519#candidate-existing-research");
    assert.deepEqual(Object.keys(loadResearchVisits()[0]).sort(), ["code", "href", "visitedAt"]);
    clearResearchVisits();
    assert.deepEqual(loadResearchVisits(), []);
    assert.equal(state.get("other-key"), "preserved");
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  }
});

test("corrupt or unavailable browser storage does not break research navigation", () => {
  assert.deepEqual(parseResearchVisits("bad-json"), []);
  assert.deepEqual(parseResearchVisits(JSON.stringify([{ href: "/candidates/600519", visitedAt: "invalid" }, null])), []);
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, get() { throw new Error("storage disabled"); } });
  try {
    assert.doesNotThrow(() => rememberResearchVisit("/candidates/600519"));
    assert.deepEqual(loadResearchVisits(), []);
    assert.doesNotThrow(clearResearchVisits);
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  }
});
