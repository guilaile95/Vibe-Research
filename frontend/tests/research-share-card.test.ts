import assert from "node:assert/strict";
import test from "node:test";
import { researchShareCard, researchShareSvg } from "../src/lib/researchShareCard.ts";
const source = { code: "600000", name: "secret prompt", price: 11.25, quote_source: "tencent", quote_trade_date: "2026-10-09", pe_ttm: null, mcap_yi: 1400,
  account: { cash: 100000 }, portfolio: ["private"], journal: "secret", path: "/home/private", api_key: "key-secret", source_url: "https://private.example/?token=secret", fixture: true };
test("public card is a closed selected projection with source dates and missing values", () => {
  const card = researchShareCard(source, ["price", "pe_ttm"]);
  assert.deepEqual(card.facts.map(f => f.metric), ["price", "pe_ttm"]);
  assert.equal(card.facts[0].as_of, "2026-10-09");
  assert.equal(card.facts[1].as_of, null);
  assert.equal(card.facts[1].status, "MISSING");
  assert.equal(card.data_kind, "FIXTURE");
  assert.deepEqual(JSON.parse(JSON.stringify(card)), card);
  assert.doesNotMatch(JSON.stringify(card), /key-secret|private\.example|\/home\/|secret prompt|100000/);
  assert.equal("account" in card, false); assert.equal("name" in card, false);
});
test("card rejects unsafe identities and fields, preserves missing and invalid date", () => {
  for (const code of ["../../secret", "600000<script>", 600000]) assert.throws(() => researchShareCard({ ...source, code }, ["price"]));
  assert.throws(() => researchShareCard(source, []));
  // @ts-expect-error adversarial untyped request
  assert.throws(() => researchShareCard(source, ["account"]));
  for (const price of [NaN, Infinity, "12", -1, 0, 1e15]) assert.equal(researchShareCard({ ...source, price }, ["price"]).facts[0].value, null);
  assert.equal(researchShareCard({ ...source, quote_trade_date: "2026-02-30", quote_source: "private token" }, ["price"]).facts[0].as_of, null);
  assert.equal(researchShareCard({ ...source, quote_source: "private token" }, ["price"]).facts[0].source, "UNKNOWN");
});
test("SVG renders facts and as-of without active content or arbitrary strings", () => {
  const card = researchShareCard(source, ["price", "pe_ttm", "mcap_yi"]);
  const svg = researchShareSvg(card);
  assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
  assert.match(svg, /2026-10-09/); assert.match(svg, /as-of 未知/); assert.match(svg, /FIXTURE/);
  assert.equal((svg.match(/<text /g) || []).length, 9);
  assert.doesNotMatch(svg, /<script|href=|onload=|private|secret/);
  const hostile = structuredClone(card); hostile.facts[0].label = '<script>alert(1)</script>';
  assert.doesNotMatch(researchShareSvg(hostile), /script|alert/);
});
test("A52/A53 all existing private categories stay out of JSON and reprojected SVG", () => {
  const kinds = ["trade", "portfolio", "assessment", "pattern", "report", "annotation", "account_profile", "account_event", "position", "campaign", "formal_attribution", "frozen_decision", "evidence_thesis", "ai_result", "note"];
  const privateFields = Object.fromEntries(kinds.map(kind => [kind, { name: `PRIVATE_CANARY_${kind}`, value: 987654321 }]));
  const input = { ...source, ...privateFields, report_text: "PRIVATE_CANARY_REPORT_TEXT", price: 11.25 };
  const card = researchShareCard(input, ["price", "pe_ttm", "mcap_yi"]);
  const forged = { ...card, ...privateFields, facts: card.facts.map(fact => ({ ...fact, ...privateFields, source_url: "file:///private/canary" })) };
  for (const output of [JSON.stringify(card), researchShareSvg(forged)]) {
    assert.doesNotMatch(output, /PRIVATE_CANARY_|987654321|file:\/\/\//);
  }
  assert.equal(card.facts[0].value, 11.25);
  assert.equal(card.facts[1].as_of, null); // Export time never manufactures source as-of.
});
