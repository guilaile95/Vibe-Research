import assert from "node:assert/strict";
import test from "node:test";
import { clearResearchVisits, loadResearchVisits, parseResearchVisits, rememberResearchVisit, researchVisitHref, parseResearchSelection, researchSelectionHref, researchNavigationRisk, sameStockCandidateReturn } from "../src/lib/researchResume.ts";

test("resume keeps validated discovery return and section, never arbitrary candidate metadata", () => {
  const source = "/screener?mode=discovery&strategy=SWING&industry=白酒#opportunity-600519";
  const path = `/candidates/600519?${new URLSearchParams({ source: "discovery", strategy: "SWING", return_to: source, claim: "unsupported" })}#candidate-evidence-gap`;
  const result = new URL(researchVisitHref(path)!, "http://localhost");
  assert.equal(new URL(result.searchParams.get("return_to")!, "http://localhost").searchParams.get("industry"), "白酒");
  assert.equal(new URL(result.searchParams.get("return_to")!, "http://localhost").hash, "#opportunity-600519");
  assert.equal(result.searchParams.get("strategy"), "SWING");
  assert.equal(result.searchParams.get("claim"), null);
  assert.equal(result.hash, "#candidate-evidence-gap");
  assert.equal(researchVisitHref("/candidates/600519#candidate-research-check"), "/candidates/600519#candidate-research-check");
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
    rememberResearchVisit("/candidates/600519#candidate-research-check");
    assert.equal(loadResearchVisits()[0].href, "/candidates/600519#candidate-research-check");
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


test("saved question and historical round survive canonical resume without identity loss", () => {
  const question = "历史问题 /?&=#", round = "旧轮次/一?&=#";
  const path = `/candidates/600519?${new URLSearchParams({ question, round })}#candidate-research-check`;
  const result = new URL(researchVisitHref(path)!, "http://localhost");
  assert.equal(result.searchParams.get("question"), question);
  assert.equal(result.searchParams.get("round"), round);
  let normalized = path;
  for (let pass = 0; pass < 5; pass++) normalized = researchVisitHref(normalized)!;
  assert.equal(normalized, path);
});

test("invalid saved identity fails closed instead of silently becoming a different location", () => {
  for (const query of ["question=", "question=%20", "question=q&question=q", "question=q&round=r&round=r", "round=r", "question=%GG", "question=%E0%A4", `question=${"a".repeat(257)}`]) {
    assert.equal(researchVisitHref(`/candidates/600519?${query}`), null, query);
  }
  assert.ok(researchVisitHref(`/candidates/600519?question=${"a".repeat(256)}`));
});


test("locator identity matches legacy store strings without trimming or double decoding", () => {
  for (const value of [" 前后空格 ", "a/b", "a%2Fb", "a+b", "问题?&=#", "\uFFFD", "a".repeat(256)]) {
    const search = `?${new URLSearchParams({ question: value, round: value })}`;
    assert.deepEqual(parseResearchSelection(search), { status: "selected", questionId: value, roundId: value });
    assert.equal(researchSelectionHref(`/candidates/600519${search}`, value, value), `/candidates/600519${search}`);
  }
  assert.deepEqual(parseResearchSelection("?question=a%252Fb"), { status: "selected", questionId: "a%2Fb", roundId: null });
  assert.deepEqual(parseResearchSelection("?question=%FF"), { status: "invalid" });
  assert.deepEqual(parseResearchSelection("?question=%EF%BF%BD"), { status: "selected", questionId: "\uFFFD", roundId: null });
});

test("navigation risk distinguishes read positions, affected check drafts and leaving both editors", () => {
  const here = { pathname: "/candidates/600519", search: "?question=q&round=r1&return_to=%2Fwatchlist" };
  assert.equal(researchNavigationRisk(here, { ...here, search: "?question=q&round=r2&return_to=%2Fwatchlist" }), "none");
  assert.equal(researchNavigationRisk(here, { ...here, search: "?question=other&return_to=%2Fwatchlist" }), "question");
  assert.equal(researchNavigationRisk(here, { ...here, search: "?return_to=%2Fwatchlist" }), "question");
  assert.equal(researchNavigationRisk(here, { ...here, search: "?question=q&round=r1&return_to=%2Fnotes" }), "page");
  assert.equal(researchNavigationRisk(here, { ...here, pathname: "/candidates/000001" }), "page");
  assert.equal(researchNavigationRisk(here, { ...here, search: "?question=q&round=&return_to=%2Fwatchlist" }), "question");
});

test("same-stock Candidate return converges across five StockData roundtrips", () => {
  let href = "/candidates/600519?return_to=%2Fwatchlist&question=q&round=r#candidate-research-check";
  for (let i = 0; i < 5; i++) {
    const data = `/stock-data?${new URLSearchParams({ code: "600519", return_to: href })}`;
    href = sameStockCandidateReturn(new URL(data, "http://localhost").searchParams.get("return_to")!, "600519")!;
  }
  assert.equal(href, "/candidates/600519?return_to=%2Fwatchlist&question=q&round=r#candidate-research-check");
  for (const target of [href.replace("600519", "000001"), "//evil.example", "/candidates/600519?question=q&round=", "/stock-data?code=600519"]) assert.equal(sameStockCandidateReturn(target, "600519"), null);
});
